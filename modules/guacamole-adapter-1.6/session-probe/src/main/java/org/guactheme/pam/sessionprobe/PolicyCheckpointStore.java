/* SPDX-License-Identifier: Apache-2.0 */
package org.guactheme.pam.sessionprobe;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.regex.*;

/** Linux/single-writer test store. Missing state is NEVER bootstrapped here. */
final class PolicyCheckpointStore {
    private static final Set<PosixFilePermission> DIRECTORY=PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> FILE=PosixFilePermissions.fromString("rw-------");
    private static final Pattern POLICY=Pattern.compile(
        "schemaVersion=1\\ngeneration=([1-9][0-9]{0,8})\\nmode=(sharing-control|enforce)\\n");
    private final Path root;
    private long knownGeneration;
    private String knownMode="enforce";

    static final class Result {
        final boolean healthy;
        final long generation;
        final String mode;
        Result(boolean healthy,long generation,String mode) {
            this.healthy=healthy; this.generation=generation; this.mode=mode;
        }
    }

    PolicyCheckpointStore(String directory) { root=directory==null ? null : Paths.get(directory).toAbsolutePath().normalize(); }

    private void privatePath(Path path,boolean directory) throws IOException {
        for (Path part=path;part!=null;part=part.getParent())
            if (Files.isSymbolicLink(part)) throw new IOException("Unsafe checkpoint path");
        if (directory ? !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)
                      : !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)) throw new IOException("Required checkpoint path missing");
        if (!Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS).equals(directory?DIRECTORY:FILE))
            throw new IOException("Unsafe checkpoint permissions");
        UserPrincipal expected=path.getFileSystem().getUserPrincipalLookupService()
            .lookupPrincipalByName(System.getProperty("user.name"));
        if (!Files.getOwner(path,LinkOption.NOFOLLOW_LINKS).equals(expected)) throw new IOException("Checkpoint owner mismatch");
    }

    private static String readSmall(Path path) throws IOException {
        try (FileChannel channel=FileChannel.open(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer bytes=ByteBuffer.allocate(513);
            while (bytes.hasRemaining() && channel.read(bytes)!=-1) { }
            if (bytes.position()>512) throw new IOException("Checkpoint too large");
            return new String(bytes.array(),0,bytes.position(),StandardCharsets.US_ASCII);
        }
    }

    static String digest(String policy) throws Exception {
        StringBuilder result=new StringBuilder();
        for (byte item:MessageDigest.getInstance("SHA-256").digest(policy.getBytes(StandardCharsets.US_ASCII)))
            result.append(String.format("%02x",item & 0xff));
        return result.toString();
    }

    private void syncDirectory() throws IOException {
        try (FileChannel directory=FileChannel.open(root,StandardOpenOption.READ)) { directory.force(true); }
    }

    private void commit(String policy,Path checkpoint) throws Exception {
        Path temporary=root.resolve(".checkpoint-"+UUID.randomUUID().toString());
        try {
            Set<OpenOption> options=new HashSet<OpenOption>(Arrays.asList(
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS));
            try (FileChannel output=FileChannel.open(temporary,options,PosixFilePermissions.asFileAttribute(FILE))) {
                ByteBuffer bytes=ByteBuffer.wrap((policy+"sha256="+digest(policy)+"\n").getBytes(StandardCharsets.US_ASCII));
                while (bytes.hasRemaining()) output.write(bytes);
                output.force(true);
            }
            Files.move(temporary,checkpoint,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            syncDirectory();
        }
        finally { Files.deleteIfExists(temporary); }
    }

    synchronized Result evaluate(String candidate) {
        try {
            if (root==null) return new Result(false,knownGeneration,knownMode);
            privatePath(root,true);
            Path lockPath=root.resolve("policy.lock"),checkpoint=root.resolve("policy.checkpoint");
            privatePath(lockPath,false);
            try (FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
                 FileLock lock=channel.tryLock()) {
                if (lock==null) return new Result(false,knownGeneration,knownMode);
                privatePath(checkpoint,false);
                String stored=readSmall(checkpoint);
                int split=stored.indexOf("sha256=");
                if (split<0) return new Result(false,knownGeneration,knownMode);
                String original=stored.substring(0,split),checksum=stored.substring(split);
                Matcher disk=POLICY.matcher(original);
                if (!disk.matches() || !checksum.equals("sha256="+digest(original)+"\n"))
                    return new Result(false,knownGeneration,knownMode);
                long diskGeneration=Long.parseLong(disk.group(1)); String diskMode=disk.group(2);
                if (diskGeneration<knownGeneration || (diskGeneration==knownGeneration && !diskMode.equals(knownMode)))
                    return new Result(false,knownGeneration,knownMode);
                knownGeneration=diskGeneration; knownMode=diskMode;
                if (candidate==null) return new Result(false,knownGeneration,knownMode);
                Matcher proposed=POLICY.matcher(candidate);
                if (!proposed.matches()) return new Result(false,knownGeneration,knownMode);
                long next=Long.parseLong(proposed.group(1)); String mode=proposed.group(2);
                if (next<knownGeneration || (next==knownGeneration && !mode.equals(knownMode)))
                    return new Result(false,knownGeneration,knownMode);
                if (next>knownGeneration) commit(candidate,checkpoint);
                // Never return success if the directory cannot be synced, even
                // after an earlier rename succeeded but its fsync failed.
                syncDirectory();
                knownGeneration=next; knownMode=mode;
                return new Result(true,knownGeneration,knownMode);
            }
        }
        catch (Exception failure) { return new Result(false,knownGeneration,knownMode); }
    }
}
