/* SPDX-License-Identifier: Apache-2.0 */
package org.guactheme.pam.sessionprobe;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.regex.*;
import javax.ws.rs.*;
import javax.ws.rs.core.MediaType;
import javax.ws.rs.core.Response;
import org.apache.guacamole.*;
import org.apache.guacamole.net.GuacamoleTunnel;
import org.apache.guacamole.net.DelegatingGuacamoleTunnel;
import org.apache.guacamole.net.auth.*;
import org.apache.guacamole.net.auth.credentials.UserCredentials;
import org.apache.guacamole.protocol.GuacamoleClientInformation;

/**
 * TEST ONLY: context-bound one-use launches and local tunnel deadlines.
 * In-memory synthetic JDBC fixture, not a grant/policy/production adapter.
 */
public final class SessionProbeProvider extends AbstractAuthenticationProvider {
    private final Set<State> states = Collections.newSetFromMap(new ConcurrentHashMap<State,Boolean>());
    private final ConcurrentMap<String,Lease> shareParents = new ConcurrentHashMap<String,Lease>();
    private final ConcurrentMap<GuacamoleTunnel,Lease> sharedTunnels = new ConcurrentHashMap<GuacamoleTunnel,Lease>();
    private final String policyFile = System.getenv("PAM_SESSION_PROBE_POLICY_FILE");
    private final PolicyCheckpointStore checkpointStore = new PolicyCheckpointStore(System.getenv("PAM_SESSION_PROBE_STATE_DIR"));
    private long policyGeneration;
    private String policyMode="enforce";
    private final ScheduledExecutorService policyWatcher;
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(task -> {
        Thread thread = new Thread(task, "pam-session-probe"); thread.setDaemon(true); return thread;
    });

    public SessionProbeProvider() {
        // Separate from the lease clock: policy I/O must not hold up deadlines.
        policyWatcher=Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread=new Thread(task,"pam-sharing-policy-probe"); thread.setDaemon(true); return thread;
        });
        policyWatcher.scheduleWithFixedDelay(() -> reconcileShared(),100,100,TimeUnit.MILLISECONDS);
    }

    private static final class Policy {
        final boolean healthy, control;
        final long generation;
        Policy(boolean healthy,boolean control,long generation) {
            this.healthy=healthy; this.control=control; this.generation=generation;
        }
    }

    private synchronized Policy policy() {
        if (policyFile == null) return new Policy(true,false,0);
        String candidate=null;
        try {
            java.nio.file.Path path=Paths.get(policyFile);
            if (!Files.isSymbolicLink(path) && Files.isRegularFile(path) && Files.size(path)<=256) {
                byte[] bytes=Files.readAllBytes(path);
                if (bytes.length<=256) candidate=new String(bytes,StandardCharsets.US_ASCII);
            }
        }
        catch (Exception failure) { /* required policy remains unavailable */ }
        PolicyCheckpointStore.Result result=checkpointStore.evaluate(candidate);
        policyGeneration=result.generation; policyMode=result.mode;
        return new Policy(result.healthy,result.healthy && "sharing-control".equals(result.mode)
            && "fixture-only".equals(System.getenv("PAM_SESSION_PROBE_ENABLED")),result.generation);
    }

    private void requirePolicy() throws GuacamoleException {
        if (!policy().healthy) throw deny("POLICY_UNAVAILABLE");
    }

    private static String shareDigest(String key) throws GuacamoleException {
        try {
            byte[] hash=MessageDigest.getInstance("SHA-256").digest(key.getBytes(StandardCharsets.UTF_8));
            StringBuilder result=new StringBuilder();
            for (byte item:hash) result.append(String.format("%02x",item & 0xff));
            return result.toString();
        }
        catch (Exception failure) { throw deny("SHARING_DENIED"); }
    }

    private Lease parentLease(String nativeId) throws GuacamoleException {
        for (State state:states) for (Lease lease:state.leases.values())
            if (lease.tunnel.getUUID().toString().equals(nativeId) && lease.open()) return lease;
        throw deny("SHARING_DENIED");
    }

    private void closeShared(GuacamoleTunnel tunnel,Lease parent) throws GuacamoleException {
        tunnel.close();
        if (!tunnel.isOpen()) {
            sharedTunnels.remove(tunnel); parent.children.remove(tunnel);
        }
    }

    private void reconcileShared() {
        Policy current=policy();
        for (Map.Entry<GuacamoleTunnel,Lease> entry:sharedTunnels.entrySet()) {
            GuacamoleTunnel tunnel=entry.getKey(); Lease parent=entry.getValue();
            if (!current.healthy || !current.control || !parent.open() || !tunnel.isOpen()) {
                try { closeShared(tunnel,parent); } catch (GuacamoleException failure) { /* retry next poll */ }
            }
        }
    }

    private GuacamoleTunnel trackShared(GuacamoleTunnel tunnel,Lease parent) throws GuacamoleException {
        parent.children.add(tunnel); sharedTunnels.put(tunnel,parent);
        Policy current=policy();
        if (!current.healthy || !current.control || !parent.open()) {
            closeShared(tunnel,parent); throw deny("SHARING_DENIED");
        }
        return new DelegatingGuacamoleTunnel(tunnel) {
            @Override public void close() throws GuacamoleException { closeShared(tunnel,parent); }
        };
    }

    public String getIdentifier() { return "pam-session-probe"; }

    /** Availability only, never identity/MFA evidence. Private upstream only. */
    @Override public Object getResource() { return new IngressResource(); }

    public final class IngressResource {
        @GET @Path("ingress-ready")
        public Response ready() {
            boolean enabled="fixture-only".equals(System.getenv("PAM_SESSION_PROBE_ENABLED"));
            boolean ready=enabled && policyFile!=null && policy().healthy;
            return Response.status(ready?204:503).header("Cache-Control","no-store").build();
        }
    }

    private static GuacamoleSecurityException deny(String code) {
        return new GuacamoleSecurityException("PAM_SESSION_PROBE_" + code);
    }

    private static String principal(UserContext context, AuthenticatedUser user) {
        return user.getAuthenticationProvider().getIdentifier()+"\0"+user.getIdentifier()+"\0"
                +context.getAuthenticationProvider().getIdentifier()+"\0"+context.self().getIdentifier();
    }

    @Override
    public UserContext decorate(UserContext context, AuthenticatedUser user, Credentials ignored)
            throws GuacamoleException {
        State state = new State(principal(context,user),
            "fixture-only".equals(System.getenv("PAM_SESSION_PROBE_ENABLED"))
            && "postgresql".equals(user.getAuthenticationProvider().getIdentifier())
            && "postgresql".equals(context.getAuthenticationProvider().getIdentifier())
            && user.getIdentifier().startsWith("gtm-")
            && user.getIdentifier().equals(context.self().getIdentifier()));
        states.add(state);
        return new Context(context,state);
    }

    @Override
    public UserContext redecorate(UserContext previous, UserContext context,
            AuthenticatedUser user, Credentials ignored) throws GuacamoleException {
        if (previous instanceof Context) {
            State state = ((Context) previous).state;
            if (state.principal.equals(principal(context,user))) return new Context(context,state);
        }
        return decorate(context,user,ignored);
    }

    @Override
    public void shutdown() {
        timer.shutdownNow(); policyWatcher.shutdownNow();
        for (State state : states) for (Lease lease : state.leases.values()) lease.close("SHUTDOWN");
        states.clear(); shareParents.clear(); sharedTunnels.clear();
    }

    private static final class Intent {
        final String asset;
        final long expiresNanos, leaseMillis;
        final AtomicBoolean consumed = new AtomicBoolean();
        Intent(String asset,long ttl,long lease) {
            this.asset=asset; this.expiresNanos=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(ttl);
            this.leaseMillis=lease;
        }
    }

    private static final class State {
        final String principal;
        final boolean fixture;
        boolean revoked;
        final Map<String,Intent> intents = new HashMap<String,Intent>();
        final ConcurrentMap<String,Lease> leases = new ConcurrentHashMap<String,Lease>();
        State(String principal,boolean fixture) { this.principal=principal; this.fixture=fixture; }
        synchronized void requireLive() throws GuacamoleException {
            if (!fixture || revoked) throw deny("CONTEXT_DENIED");
        }
        synchronized String issue(String asset,long ttl,long duration) throws GuacamoleException {
            requireLive();
            intents.values().removeIf(intent -> intent.expiresNanos <= System.nanoTime());
            if (intents.size() >= 16) throw deny("CAPACITY");
            String id="pam-intent-"+UUID.randomUUID().toString();
            intents.put(id,new Intent(asset,ttl,duration));
            return id;
        }
        synchronized Intent find(String id) throws GuacamoleException {
            requireLive();
            Intent intent=intents.get(id);
            if (intent == null) throw deny("INTENT_DENIED");
            return intent;
        }
        synchronized Intent consume(String id) throws GuacamoleException {
            Intent intent=find(id);
            if (intent.expiresNanos <= System.nanoTime() || !intent.consumed.compareAndSet(false,true))
                throw deny("INTENT_DENIED");
            return intent;
        }
    }

    private final class Lease {
        final String id=UUID.randomUUID().toString();
        final GuacamoleTunnel tunnel;
        final String asset;
        final long deadlineNanos;
        final String startedAt, deadlineAt;
        String status="ACTIVE", reason="";
        String requestedAt, confirmedAt;
        ScheduledFuture<?> deadline;
        final Set<GuacamoleTunnel> children=Collections.newSetFromMap(new ConcurrentHashMap<GuacamoleTunnel,Boolean>());
        Lease(GuacamoleTunnel tunnel,long duration,String asset) {
            this.tunnel=tunnel;this.asset=asset;
            java.time.Instant started=java.time.Instant.now();
            startedAt=started.toString(); deadlineAt=started.plusMillis(duration).toString();
            deadlineNanos=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(duration);
        }
        synchronized void close(String why) {
            if ("ENDED".equals(status)) return;
            status="TERMINATING"; reason=why;
            if (requestedAt == null) requestedAt=java.time.Instant.now().toString();
            try {
                for (GuacamoleTunnel child:children) {
                    try { closeShared(child,this); } catch (GuacamoleException failure) { /* reflected below */ }
                }
                tunnel.close();
                if (!tunnel.isOpen() && children.isEmpty()) {
                    status="ENDED"; confirmedAt=java.time.Instant.now().toString();
                    if (deadline != null) deadline.cancel(false);
                }
                else status="FAILED";
            }
            catch (GuacamoleException failure) { status="FAILED"; }
        }
        synchronized boolean open() { return "ACTIVE".equals(status) && tunnel.isOpen(); }
        synchronized Map<String,Object> view() {
            Map<String,Object> result=new LinkedHashMap<String,Object>();
            result.put("id",id); result.put("status",status); result.put("reason",reason);
            result.put("startedAt",startedAt); result.put("deadlineAt",deadlineAt);
            result.put("terminationRequestedAt",requestedAt); result.put("terminationConfirmedAt",confirmedAt);
            return result;
        }
    }

    private interface Wrapper<T> { T wrap(T value) throws GuacamoleException; }
    private static class DirectoryView<T extends Identifiable> extends DelegatingDirectory<T> {
        final Wrapper<T> wrapper;
        DirectoryView(Directory<T> directory,Wrapper<T> wrapper) { super(directory); this.wrapper=wrapper; }
        public T get(String id) throws GuacamoleException {
            T value=super.get(id); return value == null ? null : wrapper.wrap(value);
        }
        public Collection<T> getAll(Collection<String> ids) throws GuacamoleException {
            Collection<T> result=new ArrayList<T>();
            for (T value:super.getAll(ids)) result.add(wrapper.wrap(value));
            return result;
        }
        public void tryAtomically(final AtomicDirectoryOperation<T> operation) throws GuacamoleException {
            getDelegateDirectory().tryAtomically((atomic,directory) ->
                operation.executeOperation(atomic,new DirectoryView<T>(directory,wrapper)));
        }
    }

    private final class Context extends DelegatingUserContext {
        final State state;
        final UserContext nativeContext;
        Context(UserContext context,State state) { super(context); this.nativeContext=context; this.state=state; }
        Policy policyStatus() { return policy(); }
        void requireHealthyPolicy() throws GuacamoleException { requirePolicy(); }

        @Override
        public Object getResource() { return new RootResource(this); }

        @Override
        public Directory<Connection> getConnectionDirectory() throws GuacamoleException {
            final Directory<Connection> original=super.getConnectionDirectory();
            return new DirectoryView<Connection>(original, value -> guarded(value,null)) {
                @Override
                public Connection get(String id) throws GuacamoleException {
                    if (id.startsWith("pam-intent-")) {
                        Intent intent=state.find(id);
                        Connection value=original.get(intent.asset);
                        if (value == null) throw deny("ASSET_DENIED");
                        return guarded(value,id);
                    }
                    return super.get(id);
                }
            };
        }

        Connection guarded(Connection value,final String intentId) {
            return new DelegatingConnection(value) {
                @Override
                public GuacamoleTunnel connect(GuacamoleClientInformation info,Map<String,String> tokens)
                        throws GuacamoleException {
                    requirePolicy();
                    if (intentId == null) {
                        Policy current=policy();
                        if ("postgresql-shared".equals(nativeContext.getAuthenticationProvider().getIdentifier())
                                && current.healthy && current.control) {
                            Lease parent=shareParents.get(shareDigest(value.getIdentifier()));
                            if (parent == null || !parent.open()) throw deny("SHARING_DENIED");
                            return trackShared(value.connect(info,tokens),parent);
                        }
                        throw deny("NATIVE_DENIED");
                    }
                    Intent intent=state.consume(intentId);
                    // Re-query native access just before connect. This is NOT
                    // a substitute for the future authoritative PAM policy.
                    Connection current=nativeContext.getConnectionDirectory().get(intent.asset);
                    if (current == null) throw deny("ASSET_DENIED");
                    final Lease lease=new Lease(current.connect(info,tokens),intent.leaseMillis,intent.asset);
                    synchronized (state) {
                        if (state.revoked || !policy().healthy) {
                            lease.close(state.revoked ? "REVOKED" : "POLICY_UNAVAILABLE");
                            throw deny("CONTEXT_DENIED");
                        }
                        state.leases.put(lease.id,lease);
                        lease.deadline=timer.schedule(() -> lease.close("DEADLINE"),
                            Math.max(0L,lease.deadlineNanos-System.nanoTime()),TimeUnit.NANOSECONDS);
                    }
                    return new DelegatingGuacamoleTunnel(lease.tunnel) {
                        @Override public void close() { lease.close("CLIENT_CLOSED"); }
                    };
                }
                @Override @Deprecated
                public GuacamoleTunnel connect(GuacamoleClientInformation info) throws GuacamoleException {
                    return connect(info,Collections.<String,String>emptyMap());
                }
            };
        }

        @Override
        public Directory<ConnectionGroup> getConnectionGroupDirectory() throws GuacamoleException {
            return new DirectoryView<ConnectionGroup>(super.getConnectionGroupDirectory(), value ->
                new DelegatingConnectionGroup(value) {
                    public GuacamoleTunnel connect(GuacamoleClientInformation info,Map<String,String> tokens)
                            throws GuacamoleException { throw deny("GROUP_DENIED"); }
                    @Deprecated public GuacamoleTunnel connect(GuacamoleClientInformation info)
                            throws GuacamoleException { throw deny("GROUP_DENIED"); }
                });
        }

        @Override
        public Directory<ActiveConnection> getActiveConnectionDirectory() throws GuacamoleException {
            return new DirectoryView<ActiveConnection>(super.getActiveConnectionDirectory(),value -> new ActiveConnection() {
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
                public void setUsername(String name) { value.setUsername(name); }
                public GuacamoleTunnel getTunnel() { return null; }
                public void setTunnel(GuacamoleTunnel tunnel) { throw new UnsupportedOperationException("Test probe"); }
                public GuacamoleTunnel connect(GuacamoleClientInformation info,Map<String,String> tokens)
                        throws GuacamoleException {
                    state.requireLive(); Policy current=policy();
                    if (!current.healthy || !current.control) throw deny("ACTIVE_DENIED");
                    Lease parent=parentLease(value.getIdentifier());
                    return trackShared(value.connect(info,tokens),parent);
                }
                public UserCredentials getSharingCredentials(String id)
                        throws GuacamoleException {
                    state.requireLive(); Policy current=policy();
                    if (!current.healthy || !current.control) throw deny("SHARING_DENIED");
                    Lease parent=parentLease(value.getIdentifier());
                    UserCredentials credentials=value.getSharingCredentials(id);
                    Map<String,String> values=credentials.getValues();
                    if (values.size()!=1 || !values.containsKey("key")) throw deny("SHARING_DENIED");
                    shareParents.put(shareDigest(values.get("key")),parent);
                    return credentials;
                }
            });
        }

        @Override
        public UserContext getPrivileged() {
            UserContext privileged=super.getPrivileged();
            return privileged == null ? null : new Context(privileged,state);
        }
    }

    public static final class RootResource {
        private final Context context;
        RootResource(Context context) { this.context=context; }
        @Path("pam-session-probe")
        public ProbeResource probe() { return new ProbeResource(context); }
    }

    @Produces(MediaType.APPLICATION_JSON) @Consumes(MediaType.APPLICATION_JSON)
    public static final class ProbeResource {
        private final Context context;
        ProbeResource(Context context) { this.context=context; }

        @GET @Path("policy")
        public Map<String,Object> health() throws GuacamoleException {
            if (!context.state.fixture) throw deny("CONTEXT_DENIED");
            Policy policy=context.policyStatus();
            Map<String,Object> result=new LinkedHashMap<String,Object>();
            result.put("healthy",policy.healthy); result.put("generation",policy.generation);
            result.put("sharingControl",policy.control); return result;
        }

        @POST @Path("intents")
        public Map<String,Object> issue(Map<String,Object> request) throws GuacamoleException {
            if (request == null || !request.keySet().equals(new HashSet<String>(Arrays.asList("connectionId","ttlMillis","leaseMillis"))))
                throw new GuacamoleClientException("Invalid probe request");
            Object asset=request.get("connectionId"), ttl=request.get("ttlMillis"), lease=request.get("leaseMillis");
            if (!(asset instanceof String) || !((String)asset).matches("[0-9]{1,8}")
                    || !(ttl instanceof Integer || ttl instanceof Long)
                    || !(lease instanceof Integer || lease instanceof Long)) throw new GuacamoleClientException("Invalid probe request");
            long ttlMs=((Number)ttl).longValue(), leaseMs=((Number)lease).longValue();
            if (ttlMs < 1 || ttlMs > 10000 || leaseMs < 500 || leaseMs > 60000)
                throw new GuacamoleClientException("Probe duration outside test bounds");
            context.state.requireLive(); context.requireHealthyPolicy();
            if (context.nativeContext.getConnectionDirectory().get((String)asset) == null) throw deny("ASSET_DENIED");
            return Collections.<String,Object>singletonMap("connectionId",context.state.issue((String)asset,ttlMs,leaseMs));
        }

        @GET @Path("leases")
        public Collection<Map<String,Object>> list() throws GuacamoleException {
            if (!context.state.fixture) throw deny("CONTEXT_DENIED");
            Collection<Map<String,Object>> result=new ArrayList<Map<String,Object>>();
            for (Lease lease:context.state.leases.values()) result.add(lease.view());
            return result;
        }

        /** Fixture-only own-login playback without giving asset UPDATE. */
        @GET @Path("leases/{id}/recording") @Produces(MediaType.APPLICATION_OCTET_STREAM)
        public Response recording(@PathParam("id") String id) throws GuacamoleException {
            context.state.requireLive();context.requireHealthyPolicy();
            if (!"fixture-only".equals(System.getenv("PAM_SESSION_PROBE_RECORDING_ENABLED")))
                throw deny("RECORDING_UNAVAILABLE");
            Lease lease=context.state.leases.get(id);
            if (lease==null) throw deny("RECORDING_UNAVAILABLE");
            synchronized (lease) {
                if (!"ENDED".equals(lease.status) || lease.confirmedAt==null || lease.tunnel.isOpen())
                    throw deny("RECORDING_UNAVAILABLE");
            }
            // Privilege is used ONLY to read this already-owned lease's native
            // history metadata. Never return a privileged context or directory.
            UserContext privileged=context.nativeContext.getPrivileged();
            if (privileged==null) throw deny("RECORDING_UNAVAILABLE");
            if (context.nativeContext.getConnectionDirectory().get(lease.asset)==null) throw deny("RECORDING_UNAVAILABLE");
            Connection historyAsset=privileged.getConnectionDirectory().get(lease.asset);
            if (historyAsset==null) throw deny("RECORDING_UNAVAILABLE");
            // JDBC's REST record identifier is numeric, distinct from UUID.
            // Bound prototype lookup to the newest 128 records for this asset;
            // if the exact UUID is absent, deny instead of guessing an ID.
            ConnectionRecord record=null;
            for (ConnectionRecord candidate:historyAsset.getConnectionHistory()
                    .sort(ActivityRecordSet.SortableProperty.START_DATE,true).limit(128).asCollection()) {
                if (lease.tunnel.getUUID().equals(candidate.getUUID())) { record=candidate;break; }
            }
            if (record==null || record.isActive() || record.getEndDate()==null
                    || !context.nativeContext.self().getIdentifier().equals(record.getUsername())
                    || !lease.asset.equals(record.getConnectionIdentifier())
                    || context.nativeContext.getConnectionDirectory().get(lease.asset)==null)
                throw deny("RECORDING_UNAVAILABLE");
            RecordingStore.Snapshot snapshot;
            try { snapshot=RecordingStore.read(System.getenv("PAM_SESSION_PROBE_RECORDING_ROOT"),record.getUUID()); }
            catch (Exception failure) { throw deny("RECORDING_UNAVAILABLE"); }
            // Re-check context and native access after filesystem I/O.
            context.state.requireLive();context.requireHealthyPolicy();
            if (context.nativeContext.getConnectionDirectory().get(lease.asset)==null) throw deny("RECORDING_UNAVAILABLE");
            return Response.ok(snapshot.bytes,MediaType.APPLICATION_OCTET_STREAM)
                .header("Cache-Control","private, no-store").header("X-Content-Type-Options","nosniff")
                .header("Content-Disposition","attachment; filename=recording.guac")
                .header("X-PAM-Recording-State","validated-snapshot")
                .header("X-PAM-Recording-SHA256",snapshot.sha256).build();
        }

        @POST @Path("leases/{id}/terminate")
        public Map<String,Object> terminate(@PathParam("id") String id) throws GuacamoleException {
            if (!context.state.fixture) throw deny("CONTEXT_DENIED");
            Lease lease=context.state.leases.get(id);
            if (lease == null) throw deny("LEASE_DENIED");
            lease.close("REQUESTED"); return lease.view();
        }

        @POST @Path("revoke")
        public Map<String,Object> revoke() throws GuacamoleException {
            synchronized(context.state) {
                context.state.requireLive(); context.state.revoked=true;
            }
            for (Lease lease:context.state.leases.values()) lease.close("REVOKED");
            return Collections.<String,Object>singletonMap("revoked",true);
        }
    }
}
