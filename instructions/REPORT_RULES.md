# Reporting Rules (all roles)

1. **Name the subject.** Start with who (role, model), on which machine (GPU generation, cloud VM or on-site node), and which library at what maturity (prototype, fused kernel, production) the result is about.
2. **State the conditions.** In one line: what was fixed (sizes, repetitions, clocks, value ranges) and what varied (problem-size series, method).
3. **Keep negative conclusions within their conditions.** Do not widen the subject ("impossible on GPU X", "method Y is worse"). Close a question only with a proof or with a measurement under stated conditions.
4. **Cross-check.** SE audits the reports of the other roles for rules 1 to 3 and sends back any report whose subject was swapped or widened. PM applies the corrections before reporting to the user.
5. **Give numbers with units and how they were measured.** Keep estimates and measurements apart.
