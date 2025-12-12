# Reflection – TerraFix

A look at what I actually learned, what broke along the way, and how I’d build this differently next time.

## Where I Started vs. Where I Landed
On Day 1, my main goal was to avoid the "Delve" trap of direct AWS mutations. I wanted to stay at the IaC layer so that PR reviews would remain the control plane. I picked Python 3.14 and Bedrock Claude, targeting a flow of Vanta → Terraform → GitHub.

Midway through, I had to pivot. The first version felt too brittle and lacked visibility, so I basically rebuilt it from scratch. I added structured logging, typed configuration, and a much clearer orchestration loop.

Now, the end-to-end pipeline actually works: it polls Vanta, dedupes findings in Redis, clones the Terraform repo, analyzes HCL, and uses Claude to generate fixes. It even runs `terraform fmt` and opens PRs with review checklists. The whole thing is containerized for ECS/Fargate with proper health and metrics endpoints.

## What Went Wrong (and Why)
**HCL parsing crashes:**
`python-hcl2` completely choked on malformed module blocks in some sample repos. At first, this would abort the entire pipeline. I had to add defensive parsing and warning logs so that a single bad file doesn't tank the whole run. This really drove home the course lesson on isolating serial bottlenecks: don't let one bad shard kill the job.

**Dedup gaps on restarts:**
I started with SQLite for state, but it was ephemeral. Every time a worker restarted, it would reprocess old failures. Moving to Redis with `SET NX` and a TTL gave me the atomicity and persistence I needed, which aligned perfectly with the "stateless service + external state" concept from the load balancer notes.

**Unbounded tail latency:**
Sometimes Bedrock or GitHub would spike, and the worker would just hang. Implementing token-bucket rate limiting, the metrics collector with p50/p95/p99 timings, and backoffs made those long tails explicit.

**Load testing was way less easy than the guide implies:**
I *did* get all the experiments to run and generate reports/charts, but I ran into some annoying footguns that made parts of the results less clean than I wanted:

1. **LocalStack can’t emulate Bedrock** (so mock mode is mandatory):
   The guide calls this out, but the consequence is bigger than it sounds: it means the experiments mainly validate **HTTP + orchestration + Redis state** under load, not the real “AI inference is slow/expensive” bottleneck that would dominate production. This was a major issue because the latency and cost of using any SOTA reasoning LLMs are too high to be included in the load-test experiments.

2. **Docs drift on env vars (easy to waste time here):**
   The guide uses `MOCK_LATENCY_MS` / `MOCK_FAILURE_RATE`, but the API server reads `TERRAFIX_MOCK_LATENCY_MS` / `TERRAFIX_MOCK_FAILURE_RATE`. That mismatch is the kind of tiny detail that turns into 30 minutes of “why isn’t anything changing?”

3. **Failure injection didn’t actually inject failures in the run output:**
   My “resilience_failures (10% failures)” config only passed the failure-rate env var into the **Locust** process, not the **API server** process. The artifacts in `experiment_results/` show **0 failures / 0 exceptions** across the board — which is good for uptime, but it also means that run didn’t validate retry/recovery behavior the way the spec intended.

4. **Scalability runs weren’t truly size-isolated:**
   I labeled runs as small/medium/large, but the Locust user class for scalability randomly cycles sizes per request, so those runs are more like “mixed traffic with the same user count.” That’s why the “size” curves don’t separate much in the results.

5. **One of the generated charts is straight-up blank:**
   The latency heatmap image generated as an empty plot in this run. Not a catastrophic failure, but it’s a reminder that reporting code needs tests too, or you end up trusting a chart that literally contains no data.

**Vanta API access wall:**
A major roadblock I didn't anticipate: Vanta doesn't offer self-service signup. You have to [request a demo](https://www.vanta.com/pricing) and go through their enterprise sales process to get API credentials. This meant I couldn't do a proper end-to-end test with a live Vanta environment within the project timeline. The Vanta client is implemented based on their public API docs and tested with mocks, but I never got to validate against real compliance failure data from a live Vanta account. This is a significant gap—if I were to continue this project, securing enterprise API access would be the first priority.

## Concepts from the Course Applied Here
*   **Event thinking vs. CRUD:** Vanta failures come in as a stream, so TerraFix effectively builds a read model (deduped failures + PR state). It feels a lot like the event-sourcing/CQRS split we discussed.
*   **CAP and eventual consistency:** Since I'm polling, I have to accept some staleness. Redis gives me consistency for claims, but PR visibility is eventually consistent until GitHub catches up. For compliance work, that latency is a tradeoff I'm willing to make.
*   **Tail latency obsession:** The slow parts (AI inference, git clones) dominate the runtime. Adding instrumentation and limits was my way of managing that backpressure.
*   **Horizontal scale:** Keeping workers stateless and pushing coordination to Redis means I can scale out on ECS without worrying about sticky sessions.
*   **MapReduce mindset:** Right now, Terraform analysis is single-threaded, but it's embarrassingly parallel. Ideally, I'd shard large repos across workers to cut down parsing time.

## Most Challenging Bug I Fixed
The parser hard-fail was definitely the worst. Having a malformed `.tf` file crash the production pipeline was a wake-up call. Wrapping those parse attempts in guarded try/except blocks kept the system alive and just flagged the bad file. It was a practical lesson in resilience: fail the specific unit of work, not the worker.

## Highs, Lows, and Personal Growth
**The High:** Shipping the human-in-the-loop PR flow. Seeing Claude’s fixes land in a clean PR with a checklist felt like validation of the "trust but verify" microservice principle. That was the moment the architecture felt real.

**The Low:** Procrastinated too much, got busy with other classes and TA work/grading, then I caught a fever during finals week and all this slowed down progress to a crawl. I spent wayy too long refactoring which wasted a lot of precious time.

**The Growth:** I've shifted my default approach. Now, I reach for external state, rate-limiting, and tail latency metrics before I even blame the code. The course's framing on CAP and tradeoffs has fundamentally changed how I define "done."

## What I’d Do Differently Next Time
1.  **Front-load observability:** I'd ship metrics and tracing immediately so I could actually see what's happening during experiments.
2.  **Parallelize parsing:** Treating Terraform analysis like a MapReduce job would drastically cut P95 latency on large repos.
3.  **Stronger validation loop:** I'd add `terraform plan` in a sandbox and automated PR smoke tests to catch regressions before a human ever sees the PR.
4.  **Resilience drills:** I'd script failure injection (like throttling Bedrock or GitHub) into CI to make sure my backoff logic actually works.

## Closing Note
This project forced me to actually live the course playbook: event orientation, CAP tradeoffs, tail-latency discipline, and stateless scale-out. Writing this reflection is effectively my own "reduce" step: compressing a stream of messy experiments into lessons I can actually use next time.
