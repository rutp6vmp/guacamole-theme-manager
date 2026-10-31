/* SPDX-License-Identifier: Apache-2.0 */
package org.guactheme.pam.probe;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Map;
import java.util.Date;
import java.util.logging.Logger;
import org.apache.guacamole.GuacamoleException;
import org.apache.guacamole.GuacamoleSecurityException;
import org.apache.guacamole.net.GuacamoleTunnel;
import org.apache.guacamole.net.auth.*;
import org.apache.guacamole.net.auth.credentials.UserCredentials;
import org.apache.guacamole.protocol.GuacamoleClientInformation;

/**
 * G01 experiment only. Never authenticates, grants access or opens a socket.
 * Installed deliberately in a disposable fixture, denies every connect/join.
 * This is NOT a policy engine, admission store or production PAM adapter.
 */
public final class GateProbeProvider extends AbstractAuthenticationProvider {
    private static final Logger LOG = Logger.getLogger(GateProbeProvider.class.getName());

    @Override
    public String getIdentifier() {
        return "pam-gate-probe";
    }

    private String identityProof(UserContext context, AuthenticatedUser user) {
        // Only server-provided identity objects. Never read browser claims,
        // Credentials, bearer tokens, passwords, OTP data or parameter tokens.
        String material = user.getAuthenticationProvider().getIdentifier() + "\0"
                + user.getIdentifier() + "\0"
                + context.getAuthenticationProvider().getIdentifier() + "\0"
                + context.self().getIdentifier();
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(material.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder();
            for (byte item : hash)
                result.append(String.format("%02x", item & 0xff));
            return result.toString();
        }
        catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("Required SHA-256 unavailable");
        }
    }

    @Override
    public UserContext decorate(UserContext context, AuthenticatedUser user,
            Credentials ignored) throws GuacamoleException {
        String proof = identityProof(context, user);
        LOG.info("PAM_PROBE_DECORATE proof=" + proof);
        return new GuardedContext(context, proof);
    }

    @Override
    public UserContext redecorate(UserContext previous, UserContext context,
            AuthenticatedUser user, Credentials ignored) throws GuacamoleException {
        String proof = identityProof(context, user);
        LOG.info("PAM_PROBE_REDECORATE proof=" + proof);
        return new GuardedContext(context, proof);
    }

    private static GuacamoleSecurityException denial(String kind, String proof) {
        LOG.info("PAM_PROBE_DENY kind=" + kind + " proof=" + proof);
        return new GuacamoleSecurityException("PAM_PROBE_DENY_" + kind);
    }

    private interface Mapper<T> {
        T wrap(T value) throws GuacamoleException;
    }

    /** Preserve guards for single, bulk and atomic directory reads. */
    private static final class GuardedDirectory<T extends Identifiable>
            extends DelegatingDirectory<T> {
        private final Mapper<T> mapper;

        GuardedDirectory(Directory<T> directory, Mapper<T> mapper) {
            super(directory);
            this.mapper = mapper;
        }

        @Override
        public T get(String id) throws GuacamoleException {
            T value = super.get(id);
            return value == null ? null : mapper.wrap(value);
        }

        @Override
        public Collection<T> getAll(Collection<String> ids) throws GuacamoleException {
            Collection<T> result = new ArrayList<T>();
            for (T value : super.getAll(ids))
                result.add(mapper.wrap(value));
            return result;
        }

        @Override
        public void tryAtomically(final AtomicDirectoryOperation<T> operation)
                throws GuacamoleException {
            getDelegateDirectory().tryAtomically(new AtomicDirectoryOperation<T>() {
                @Override
                public void executeOperation(boolean atomic, Directory<T> directory)
                        throws GuacamoleException {
                    operation.executeOperation(atomic, new GuardedDirectory<T>(directory, mapper));
                }
            });
        }
    }

    private static final class GuardedContext extends DelegatingUserContext {
        private final String proof;

        GuardedContext(UserContext context, String proof) {
            super(context);
            this.proof = proof;
        }

        @Override
        public Directory<Connection> getConnectionDirectory() throws GuacamoleException {
            return new GuardedDirectory<Connection>(super.getConnectionDirectory(), value ->
                new DelegatingConnection(value) {
                    @Override
                    public GuacamoleTunnel connect(GuacamoleClientInformation info,
                            Map<String, String> tokens) throws GuacamoleException {
                        throw denial("CONNECTION", proof);
                    }

                    @Override
                    @Deprecated
                    public GuacamoleTunnel connect(GuacamoleClientInformation info)
                            throws GuacamoleException {
                        throw denial("CONNECTION", proof);
                    }
                });
        }

        @Override
        public Directory<ConnectionGroup> getConnectionGroupDirectory() throws GuacamoleException {
            return new GuardedDirectory<ConnectionGroup>(super.getConnectionGroupDirectory(), value ->
                new DelegatingConnectionGroup(value) {
                    @Override
                    public GuacamoleTunnel connect(GuacamoleClientInformation info,
                            Map<String, String> tokens) throws GuacamoleException {
                        throw denial("GROUP", proof);
                    }

                    @Override
                    @Deprecated
                    public GuacamoleTunnel connect(GuacamoleClientInformation info)
                            throws GuacamoleException {
                        throw denial("GROUP", proof);
                    }
                });
        }

        @Override
        public Directory<ActiveConnection> getActiveConnectionDirectory() throws GuacamoleException {
            // Preserve authorized metadata/browsing. Only connection, sharing
            // and direct tunnel access are blocked. Real active joins remain
            // an explicit untested G01 subcase until a live target exists.
            return new GuardedDirectory<ActiveConnection>(super.getActiveConnectionDirectory(), value ->
                new ActiveConnection() {
                    public String getIdentifier() { return value.getIdentifier(); }
                    public void setIdentifier(String id) { value.setIdentifier(id); }
                    public String getConnectionIdentifier() { return value.getConnectionIdentifier(); }
                    public void setConnectionIdentifier(String id) { value.setConnectionIdentifier(id); }
                    public String getSharingProfileIdentifier() { return value.getSharingProfileIdentifier(); }
                    public void setSharingProfileIdentifier(String id) { value.setSharingProfileIdentifier(id); }
                    public Date getStartDate() { return value.getStartDate(); }
                    public void setStartDate(Date date) { value.setStartDate(date); }
                    public String getRemoteHost() { return value.getRemoteHost(); }
                    public void setRemoteHost(String host) { value.setRemoteHost(host); }
                    public String getUsername() { return value.getUsername(); }
                    public void setUsername(String username) { value.setUsername(username); }
                    public GuacamoleTunnel getTunnel() { return null; }
                    public void setTunnel(GuacamoleTunnel tunnel) { throw new UnsupportedOperationException("Test-only probe"); }
                    public GuacamoleTunnel connect(GuacamoleClientInformation info, Map<String,String> tokens)
                            throws GuacamoleException { throw denial("ACTIVE", proof); }
                    public UserCredentials getSharingCredentials(String id)
                            throws GuacamoleException { throw denial("SHARING", proof); }
                });
        }

        @Override
        public UserContext getPrivileged() {
            UserContext privileged = super.getPrivileged();
            return privileged == null ? null : new GuardedContext(privileged, proof);
        }
    }
}
