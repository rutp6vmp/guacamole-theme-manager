/* SPDX-License-Identifier: Apache-2.0 */
package org.guactheme.pam.sessionprobe;

import java.io.StringReader;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.UUID;
import org.apache.guacamole.io.ReaderGuacamoleReader;
import org.apache.guacamole.protocol.GuacamoleInstruction;

/** TEST ONLY: bounded snapshot, not durable evidence sealing or retention. */
final class RecordingStore {
    static final int LIMIT=8*1024*1024;
    static final class Snapshot {
        final byte[] bytes;
        final String sha256;
        Snapshot(byte[] bytes,String sha256) { this.bytes=bytes;this.sha256=sha256; }
    }

    static Snapshot read(String configuredRoot,UUID history) throws Exception {
        if (configuredRoot==null || history==null) throw new Exception("Recording unavailable");
        Path root=Paths.get(configuredRoot);
        if (!root.isAbsolute()) throw new Exception("Recording unavailable");
        root=root.normalize();
        Path directory=root.resolve(history.toString()),file=directory.resolve("session.guac");
        for (Path path=file;path!=null;path=path.getParent())
            if (Files.isSymbolicLink(path)) throw new Exception("Recording unavailable");
        if (!Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)
                || !Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)) throw new Exception("Recording unavailable");
        byte[] bytes;
        try (FileChannel channel=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            long size=channel.size();
            if (size<1 || size>LIMIT) throw new Exception("Recording unavailable");
            ByteBuffer buffer=ByteBuffer.allocate((int)size);
            while (buffer.hasRemaining()) if (channel.read(buffer)==-1) throw new Exception("Recording unavailable");
            if (channel.size()!=size) throw new Exception("Recording unavailable");
            bytes=buffer.array();
        }
        String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        ReaderGuacamoleReader reader=new ReaderGuacamoleReader(new StringReader(text));
        int consumed=0,sync=0;
        char[] frame;
        while ((frame=reader.read())!=null) {
            consumed+=frame.length;
            GuacamoleInstruction instruction=new ReaderGuacamoleReader(new StringReader(new String(frame))).readInstruction();
            if ("key".equals(instruction.getOpcode())) throw new Exception("Recording unavailable");
            if ("sync".equals(instruction.getOpcode())) sync++;
        }
        // Public ReaderGuacamoleReader permits EOF with buffered partial input.
        // Compare consumed characters to reject incomplete final instructions.
        if (consumed!=text.length() || sync<2) throw new Exception("Recording unavailable");
        StringBuilder digest=new StringBuilder();
        for (byte value:MessageDigest.getInstance("SHA-256").digest(bytes))
            digest.append(String.format("%02x",value & 0xff));
        return new Snapshot(bytes,digest.toString());
    }
}
