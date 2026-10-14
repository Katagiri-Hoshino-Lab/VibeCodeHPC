# Resource groups used by this run

Copy to `_remote_info/<site>/node_resource_groups.md` in your input directory and fill in your site's values.

| Resource group | Nodes | Per node | Max elapsed | Rate | Used for |
|---|---|---|---|---|---|
| `<queue for the organisation>` | 1 (whole node) | `<CPUs>`, `<N> x <GPU>`, `<memory>` | `<hours>` | `<points/s per node>` | the organisation's job (model server + agents) |
| `<queue for measurements>` | 1 GPU | `<cores>` | `<hours>` | `<points/s per GPU>` | GPU measurement jobs submitted with `measure_submit` |

- The organisation's job is charged by its elapsed time. Work the agents run inside it costs nothing extra.
- In ChangeLog entries, record work run inside the job with `resource_group: <queue for the organisation>` and the start/end time of the run.
