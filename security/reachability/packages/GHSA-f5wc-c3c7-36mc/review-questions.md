# Review questions — GHSA-f5wc-c3c7-36mc

Answer each with the evidence you used. An unanswered question is not a negative
answer, and a `Not present` conclusion drawn from a symbol table alone will be
rejected by `release/cve.py`.

## 1. Carrier attribution

Which installed binary carries `golang.org/x/crypto v0.46.0`?
The scan records only an ostree object digest. Candidates:

- `podman-5.8.4-1.fc44.x86_64 at /usr/sbin/podman`
- `skopeo-1.22.2-2.fc44.x86_64 at /usr/sbin/skopeo`
- `bootc-1.16.4-1.fc44.x86_64 at /usr/sbin/bootc`

## 2. The vulnerable function

Name the vulnerable source file and function from the advisory, and the feature it
belongs to. If the advisory does not identify one, say so.

## 3. Presence in the shipped build

Is the vulnerable code compiled into the installed binary? Required evidence:

- the installed NEVRA and the source RPM at the *same* version and release;
- the build configuration Fedora used, including build tags;
- a mapping from the vulnerable function to the binary, via debuginfo or debugsource.

Go's linker eliminates dead code and the compiler inlines across package boundaries.
Neither a present nor an absent module-level symbol settles this.

## 4. Reachability

If present, is there a supported or attacker-controlled path that reaches it? State:

- the command required, and the privilege it needs;
- the input type, and whether it can come from a network or an untrusted file;
- whether any enabled unit, socket, D-Bus name or desktop entry reaches it;
- whether Bunny OS exposes the feature at all.

## 5. Mitigation

If reachable, does SELinux targeted policy or systemd sandboxing materially reduce the
exploit? Name the control, analyse the bypass, and state the residual impact.

## 6. Conclusion

One of: `Not present`, `Present but unreachable`, `Reachable but mitigated`,
`Reachable and blocking`, `Unknown`.

`Unknown` is an acceptable and often correct answer. It remains blocking, which is the
current state, so concluding `Unknown` costs the project nothing it has not already
lost. A wrong `Not present` on a Critical finding would clear a blocker it should not.
