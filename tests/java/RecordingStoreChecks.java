/* SPDX-License-Identifier: Apache-2.0 */
package org.guactheme.pam.sessionprobe;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.io.RandomAccessFile;
import java.util.*;

/** Actual production validator boundary cases, with synthetic protocol bytes. */
public final class RecordingStoreChecks {
    interface Check { void run() throws Exception; }
    static int passed;
    static void refused(Check action) throws Exception {
        boolean failed=false;
        try { action.run(); } catch (Exception expected) { failed=true; }
        if (!failed) throw new AssertionError("Unsafe recording snapshot accepted");
    }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory("gtm-recording-validator-");
        UUID history=UUID.randomUUID();Path directory=root.resolve(history.toString());Files.createDirectory(directory);
        Path file=directory.resolve("session.guac");
        byte[] valid="4.size,1.0,1.1,1.1;4.name,1.繁;4.sync,1.1;4.sync,1.2;".getBytes(StandardCharsets.UTF_8);
        try {
            Files.write(file,valid);
            RecordingStore.Snapshot result=RecordingStore.read(root.toString(),history);
            if (!Arrays.equals(valid,result.bytes) || !result.sha256.matches("[a-f0-9]{64}")) throw new AssertionError("Snapshot mismatch");
            passed++;
            refused(() -> RecordingStore.read(null,history));refused(() -> RecordingStore.read("relative",history));passed++;
            refused(() -> RecordingStore.read(root.toString(),UUID.randomUUID()));passed++;
            for (byte[] bad:new byte[][]{new byte[0],new byte[]{(byte)0xff},"not protocol".getBytes(StandardCharsets.UTF_8)}) {
                Files.write(file,bad);refused(() -> RecordingStore.read(root.toString(),history));
            } passed++;
            Files.write(file,Arrays.copyOf(valid,valid.length-1));refused(() -> RecordingStore.read(root.toString(),history));passed++;
            Files.write(file,valid);Files.write(file,"4.syn".getBytes(StandardCharsets.UTF_8),StandardOpenOption.APPEND);
            refused(() -> RecordingStore.read(root.toString(),history));passed++;
            Files.write(file,"2147483648.x;".getBytes(StandardCharsets.UTF_8));refused(() -> RecordingStore.read(root.toString(),history));passed++;
            Path other=root.resolve("private-canary");Files.write(other,valid);Files.delete(file);Files.createSymbolicLink(file,other);
            refused(() -> RecordingStore.read(root.toString(),history));Files.delete(file);Files.write(file,valid);passed++;
            Path moved=root.resolve(UUID.randomUUID().toString());Files.move(directory,moved);Files.createSymbolicLink(directory,moved);
            refused(() -> RecordingStore.read(root.toString(),history));Files.delete(directory);Files.move(moved,directory);passed++;
            try (RandomAccessFile oversized=new RandomAccessFile(file.toFile(),"rw")) { oversized.setLength(RecordingStore.LIMIT+1L); }
            refused(() -> RecordingStore.read(root.toString(),history));passed++;
            Files.write(file,valid);Files.write(file,"3.key,2.65,1.1;".getBytes(StandardCharsets.UTF_8),StandardOpenOption.APPEND);
            refused(() -> RecordingStore.read(root.toString(),history));passed++;
            System.out.println("{\"suite\":\"recording-store-boundaries\",\"passed\":"+passed+"}");
        }
        finally {
            try (java.util.stream.Stream<Path> paths=Files.walk(root)) {
                for (Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator) Files.deleteIfExists(path);
            }
        }
    }
}
