**EMBER — HackHarvard 2026: track ratings, weaknesses, and improvements**

Prepared for the October 16–18, 2026 event. This consolidates our project assessment and prize strategy. It distinguishes published requirements from our judgment about what would make a competitive entry.

**Recommendation: build one excellent disaster coordination project. Prioritize Overall and Sustainability, make Photon the human interaction layer, use Chalk to prove reliability, and give Daytona a substantive simulation role. Pursue SpaceXAI only if satellite data and Grok Voice fit the working product without delaying it.**

The ratings below assess the proposed concept and its fit with each track. They are not win probabilities, implementation scores, or confirmation that an integration already works. We have not audited a working repository or verified your sponsor accounts.

**The project being assessed**

EMBER coordinates scarce emergency resources during an urban flood. It helps an emergency operations planner rescue residents, maintain critical services, and prevent environmental damage from infrastructure failures.

The prototype covers one district, roughly 100 simulated residents grouped into households, a hospital, wastewater infrastructure, a response base, a small fleet, compatible mobile generators, and qualified crews. It combines a shared operational picture with personalized calls and messages.

A resident reports an accessibility requirement or blocked pickup road. That information changes a transport assignment and may change the route or timing of an infrastructure intervention. A facility operator supplies updated backup endurance or equipment status. EMBER revises the shared allocation, checks constraints, and communicates the resulting plan to affected people.

The central contribution is the complete loop:

**Human report → updated shared state → feasible resource allocation → simulated consequences → reviewed assignments → confirmation and replanning.**

The environmental focus is preventing untreated wastewater discharge when flooding disrupts power and infrastructure. Hospital continuity, household rescue, and wastewater protection compete for limited transport, generators, and crews. The system must handle these dependencies without double-booking resources or inventing capabilities.

This is a decision-support prototype demonstrated in a simulated exercise. Real map or satellite inputs can ground the scenario; household records, operational inventories, and unverified facility parameters must be labeled synthetic or assumed.

**Ratings at a glance**

| Track or prize | Current concept rating | Strongest feature | Main weakness | Recommended priority |
| --- | ---: | --- | --- | --- |
| Overall | **6/10** | A compelling link between individual assistance and district-wide resource decisions | Broad disaster-agent claims are easy to make; novelty and execution remain unproven | Primary |
| ASUS Sustainability | **7/10** | Preventing a specific environmental consequence of infrastructure failure | Environmental impact needs a defensible model and comparative evidence | Primary |
| Photon 2.0 | **8/10** | Conversations directly change consequential, shared plans | Could collapse into a scripted intake call followed by a generic response | Deepest sponsor integration |
| Daytona | **5/10** | Isolated evaluation of alternative plans and uncertain scenarios | Parallel simulations alone can look like interchangeable hosted compute | Supporting integration |
| Chalk | **7/10** | Data freshness, agent decisions, and plan consistency create meaningful evaluation tasks | No demonstrated dataset, evaluation results, or working access yet | Strong supporting target |
| SpaceXAI | **4/10** | Satellite flood observations and a voice interface could fit naturally | The current core idea does not require a space-data contribution or Grok API | Conditional |

These scores do not add together. A coherent, reliable demonstration matters more than the number of sponsor logos.

**Requirements that apply across the competition**

The supplied 2026 Devpost requirements state:

- Submit by **8 AM ET on Sunday, October 18**. No late submissions are accepted.
- Include a **public GitHub repository created between October 16 and 18**.
- Select every track, sponsor challenge, and opt-in prize you want considered.
- Compete in person and present a live demo during Sunday judging, **9 AM–12 PM**.
- Prepare a **three-minute presentation**.
- An optional demo video of up to three minutes is recommended.
- Overall judging has four equally weighted criteria: Innovation, Creativity & Impact; Technical Complexity; Functionality & Usability; Teamwork, Collaboration & Learning.

Do not treat every assertion in informal sponsor research as an eligibility rule. In particular, the supplied text does not establish a blanket prohibition on all reused code. Follow applicable event rules, disclose dependencies and prior work accurately, and do not assume an older handbook describes the 2026 event.

**1. Overall — 6/10**

**Brutal assessment.** “AI agents optimize disaster response” is an appealing theme, but it is not enough to distinguish a winner. Infrastructure dependency models, disaster simulations, and restoration optimization already exist. A polished map with moving vehicles can also conceal a shallow backend. The project becomes strong when the judge sees an unexpected human report change a constrained allocation and can inspect the consequences.

The listed overall prizes are AirPods Max 2 for each first-place team member, Apple Watch SE for each second-place team member, and AirPods Generation 5 for each third-place team member, as stated in the supplied prize text.

| Criterion | What a strong entry demonstrates | Where EMBER stands |
| --- | --- | --- |
| Innovation, Creativity & Impact — 25% | A specific problem, distinct contribution, and credible beneficiary | Strong problem; differentiation needs the human-information-to-shared-plan loop |
| Technical Complexity — 25% | Difficult components that work together and affect outcomes | Potentially strong; agents, constraints, simulation, and communication must actually connect |
| Functionality & Usability — 25% | A reliable product someone can understand and operate | Unproven until a live perturbation changes the working system |
| Teamwork, Collaboration & Learning — 25% | Clear ownership, integration, and lessons learned | Requires an explicit team story; additional features do not substitute for it |

**Essential improvements**

1. **Define one decision problem.** Allocate a small set of vehicles, generators, and crews across household assistance and critical facilities during one flood. Avoid combining wildfire, flood, indoor evacuation, hospital operations, and regional logistics into separate products.
2. **Demonstrate one complete infrastructure cascade.** A power disruption threatens wastewater operation; deployment and setup take time; a road closure delays the intervention; updated human information changes the plan. Every stage should have an inspectable state transition.
3. **Make personalization affect allocation.** Accessibility, household size, and vehicle availability must change eligibility or capacity requirements. A personalized explanation alone is weak.
4. **Use explicit constraints.** Enforce route availability, capacities, equipment compatibility, crew qualifications, task duration, resource availability, and deadlines. Prevent double booking through a shared assignment ledger.
5. **Separate reasoning from calculation.** Agents collect information and propose actions. A deterministic allocator and simulator determine feasibility and outcomes. The language model must not invent travel times, discharge volumes, or people reached.
6. **Allow a real disruption.** Let the judge introduce a closure, declined assignment, delayed vehicle, or corrected facility report. Show the revised plan or explain why no feasible solution remains.
7. **Show a fair comparison.** Compare against a reasonable incident-by-incident allocation baseline using the same initial resources and scenario. Explain what coordination changes.
8. **Prepare the teamwork answer.** Reserve about 20 seconds to explain who built which subsystem, how you integrated it, and what you learned.

**Evidence to show:** the new report, affected constraints, resource reassignment, updated resident message, and resulting outcome comparison. One visible chain of cause and effect is more persuasive than several independent agent panels.

**Stretch assessment:** low stretch for the focused coordination loop; high stretch for a photorealistic building, whole-city simulation, multiple disaster types, or a claim of autonomous real-world emergency dispatch.

**Keep or cut:** keep the shared state, allocator, causal demo, and clear interface. Cut elaborate 3D work if it delays a credible working loop.

**2. ASUS Sustainability — 7/10**

**Brutal assessment.** The revised idea has a credible sustainability core. Its strength is avoiding an identifiable environmental failure through better emergency allocation. “We use fewer resources” remains too vague unless the system changes a concrete decision and measures its environmental consequence.

**Published requirement and theme:** address real-world environmental challenges, resource consumption, sustainable habits, or environmental impact. ASUS hardware use is encouraged; the supplied brief does not make it mandatory. Listed awards are an ASUS motherboard, a ZenScreen MB169CK-P portable monitor, and a ROG keyboard for the first-, second-, and third-place teams respectively.

**Specific user and behavior change:** an emergency planner changes the timing and allocation of compatible equipment and qualified crews to maintain wastewater service, while satisfying urgent human and essential-service requirements. Consumer shopping or household energy choices are not necessary to satisfy this theme.

**Essential improvements**

1. **Make untreated wastewater discharge the main environmental endpoint.** Report modeled cubic meters of untreated discharge during the scenario. Fuel use can be secondary. Avoid a generic sustainability score.
2. **Implement the causal model.** Represent inflow, available storage, pumping capacity, power status, and the time required to transport and install compatible equipment. Overflow follows from a flow-and-storage balance.
3. **Include downstream limits.** A powered pump does not prevent pollution if the receiving network or treatment system cannot accept the flow. State the downstream availability assumption or model its constraint.
4. **Make the environmental objective change the plan.** Show a case where two allocations satisfy the same urgent service requirements, but one prevents more untreated discharge. Also show cases where emergency human needs consume the available resources and environmental harm cannot be avoided.
5. **Use defensible inputs.** Record the source, units, and uncertainty of each parameter. Clearly label hypothetical facility capacities, backup endurance, and resource inventories.
6. **Compare under identical conditions.** Use the same hazard timeline, demand, resources, deadlines, and information availability for each policy comparison.
7. **Check sensitivity.** Vary inflow, deployment delay, backup duration, and road availability. Report whether the benefit persists or depends on one convenient assumption.

**Useful impact measures**

| Measure | Why it matters | Claim boundary |
| --- | --- | --- |
| Modeled untreated discharge, m³ | Directly connects an infrastructure decision to environmental release | Does not establish contaminant mass, ecological damage, or verified real-world avoided pollution |
| Wastewater service interruption, minutes | Explains the mechanism behind release | Service continuity and pollution prevention are related but distinct |
| Critical-service outage, minutes | Captures infrastructure resilience | Do not relabel all outage reduction as environmental benefit |
| Vehicle travel and modeled fuel use | Shows secondary resource efficiency | Include extra journeys and generator use where relevant |
| Unresolved urgent household needs | Shows the human constraints alongside environmental performance | Do not infer actual lives saved from a simulation |

Use a priority structure that protects urgent human needs and essential services before comparing environmental outcomes among feasible alternatives. Do not use an arbitrary score that trades a person against a quantity of carbon. Retain operational reserve; maximizing resource utilization to 100% can make a response brittle.

**Do not claim:** invented tons of CO₂ saved, avoided rebuilding emissions without a lifecycle model, or a measured environmental outcome when you only have a hypothetical simulation. Do not conflate wastewater, stormwater drainage, and drinking water.

**Stretch assessment:** low stretch for wastewater continuity and modeled overflow prevention; high stretch for adding chemical dispersion, forest carbon, and reconstruction emissions during the same weekend.

**Keep or cut:** keep one complete environmental mechanism with uncertainty and a baseline. Cut unrelated green features and the rejected clean-powered-shelter direction.

**Optional separate prize:** the ASUS Content Challenge requires public content, platform-specific ASUS tagging, the event hashtags, and a proof form. It is a separate submission task, not an improvement to EMBER's environmental model. Only spend time on it after the core demo is stable.

**3. Photon 2.0 — 8/10**

**Brutal assessment.** This is the strongest natural sponsor fit. Disaster coordination depends on information held by different people, changing circumstances, and confirmations. A single scripted call asking a few questions would leave most of that advantage unused.

**Published eligibility:** build on Photon 2.0 and operate on at least one Photon channel. The listed awards are $400 cash plus $300 credits and an interview fast-track for the track winner; $200 cash plus $100 credits for runner-up; and $300 cash plus $100 credits for Best Voice Agent on a Photon phone number.

Supplementary guidelines emphasize vision, craft, depth, and traction. They describe iMessage winner and runner-up categories as well as voice, while the Devpost eligibility line permits at least one supported channel. Treat the exact award routing as something to confirm with the sponsor. A judge using their own phone is a persuasive demonstration, not a published universal requirement.

**Essential improvements**

1. **Give the agent a reason to contact each person.** Ask questions whose answers could change an assignment: accessibility, pickup constraints, household size, backup endurance, equipment compatibility, or availability.
2. **Include two human roles.** Demonstrate a resident and a facility operator or responder. Their information should influence the same shared plan.
3. **Make conversations use tools.** Read the current assignment, record a report, request clarification, trigger reevaluation, and retrieve the approved revision.
4. **Keep memory across turns and channels.** After a call, a text follow-up should remember the household's constraints and refer to the current plan version.
5. **Model commitment.** An offered vehicle or accepted assignment has a different status from an unconfirmed suggestion. Replan on rejection, timeout, delay, or completion.
6. **Handle uncertainty honestly.** A phone call does not automatically establish location. Use an explicitly supplied or assigned demo location. Store who reported a closure, when, and with what confidence.
7. **Prevent stale instructions.** If the plan changes during a conversation, fetch the latest assignment before communicating it. Notify people whose earlier instructions are superseded.
8. **Polish the experience.** Natural turn-taking, concise questions, understandable next steps, low latency, and a useful failure path matter more than a long agent monologue.

**Best demonstration:** the resident reports an accessibility need and blocked pickup road; the operator corrects a facility's backup status; the allocator revises a shared plan; the resident receives a consistent follow-up. The conversation changes operations rather than merely narrating a predetermined route.

**Implementation caution:** the supplementary guidance describes voice through a Photon SMS number and a voice-provider connection. Do not assume a shared iMessage number automatically supports the same calling path. Prove an actual call early.

**Evidence to show:** working Photon channel, tool activity, persistent context, assignment status, and a follow-up reflecting the revised plan. Measure latency and conversation success on real test interactions; do not present invented performance figures.

**Stretch assessment:** very low for the communication layer; moderate for a second channel; high for adding many channels before one conversation loop is reliable.

**Keep or cut:** keep one excellent voice experience and a useful text continuation if feasible. Cut channel breadth and additional agent personalities that do not improve coordination.

**4. Daytona — 5/10**

**Brutal assessment.** The concept has a reasonable execution use case, but ordinary simulations hosted in a sandbox are not automatically a distinctive Daytona project. The strongest version makes isolated, repeatable experiments part of how the planner reaches a decision.

**Published eligibility:** Daytona must be a meaningful part of the product. The brief rewards creative and effective sandbox use. It does **not** require AI-generated or untrusted code, and it does not say the project must be impossible to run elsewhere. The prize is **$5,000 in Daytona credits**, not cash.

**Essential improvements**

1. **Use a decision-to-experiment loop.** The planner proposes candidate allocations, evaluates them in isolated runs, inspects infeasibility and outcome reports, revises a candidate, and evaluates again when appropriate.
2. **Make each run reproducible.** Package the scenario version, candidate assignments, parameter assumptions, random seed where used, and simulator version. Save the output and reason a candidate failed.
3. **Evaluate uncertainty.** Test a few credible variations such as delayed arrival, resource failure, or uncertain backup duration. Parallelism should reduce useful planning latency, not merely create visual activity.
4. **Keep inputs isolated.** Experiments should not mutate the live assignment ledger or contaminate another candidate's state.
5. **Expose meaningful runtime evidence.** Show actual run identifiers, status, inputs, outcomes, and rejected constraints. Sandbox IDs and logs support the story; they are not the user-facing product.
6. **Handle operational limits.** Bound concurrency, timeouts, retries, and cleanup. Make a failed experiment visible rather than silently accepting incomplete results.

**Strong agent task:** “Evaluate these allocations under the current road closure; identify why a critical intervention misses its deadline; propose a feasible revision; compare the new result.” This gives the execution environment a substantive role without inventing a need for runtime code generation.

If the implementation only runs fixed small jobs, describe it accurately. Do not claim that a laptop could never do the computation or that sandboxing alone is the novel contribution. Verify actual account quotas and network access rather than assuming unlimited parallel runs or downloads.

**Evidence to show:** a real runtime experiment, its reproducible inputs, constraint failure or outcome, and the resulting planning revision. Distinguish any prerecorded fallback from live execution.

**Stretch assessment:** moderate. It fits best when the simulation loop already exists. It becomes forced when disposable environments are created solely to satisfy a prize narrative.

**Keep or cut:** keep Daytona if it powers the actual evaluation path. Cut extra sandbox layers and unnecessary code generation. Do not let this integration displace the environmental model or the live conversation.

**5. Chalk — 7/10**

**Brutal assessment.** Chalk has a stronger fit than a generic “agent infrastructure add-on.” EMBER must distinguish fresh from stale information, combine contextual reports, avoid conflicting commitments, and communicate valid plans. Those are specific behaviors that can be evaluated. The weakness is that an evaluation story without a dataset and results is only a promise.

**Published eligibility:** build an agentic application using contextual or real-world data and use at least one Chalk component. The brief emphasizes impact, use of data, and evaluation. The award is **$1,500+ in Apple gift cards for the winning team**.

The supplied brief does not establish a separate universal multi-step-agent disqualification, nor does it say all synthetic contextual test data is unacceptable. However, a substantive tool-using workflow and honestly labeled data make a much stronger entry than a chat wrapper.

**Essential improvements**

1. **Choose one meaningful Chalk role.** Evaluation is the cleanest fit: run repeatable cases against the agent's handling of reports, tool choices, assignments, and updates. Add a data layer only if it solves an actual need.
2. **Build a compact benchmark.** Include ordinary cases, ambiguous reports, conflicting observations, missing values, changed constraints, and infeasible requests. Keep a held-out set for final comparison.
3. **Score behaviors precisely.** Test whether the agent preserves accessibility requirements, uses the current plan, requests missing decision-critical information, and avoids treating an unconfirmed resource as available.
4. **Use deterministic scoring where possible.** Capacity violations, double bookings, stale version references, missing required fields, and constraint violations should not depend solely on another LLM's opinion.
5. **Version the evaluation.** Pin the dataset, agent/task version, model or prompt configuration, and scorers. Show what changed between versions and which cases improved or regressed.
6. **Keep data provenance and time.** Reports need source and observation time. A new message about an old observation must not silently override more relevant current information.
7. **Inspect failures.** An aggregate success percentage is insufficient. Show a trace, the failed expectation, and the resulting correction.

| Evaluation case | Behavior worth scoring |
| --- | --- |
| Two agents request the same vehicle | Shared allocation prevents overlapping commitments |
| Resident needs accessible transport | Assignment satisfies the requirement or explicitly reports unmet need |
| New road closure affects an active plan | Plan is revised or marked infeasible; affected person gets an update |
| Old facility report arrives late | Observation time and source influence state updates |
| Generator cannot power the required equipment | Incompatible assignment is rejected |
| Operator declines an assignment | Resource and task states are corrected; replanning follows |
| No feasible rescue or infrastructure action exists | Agent identifies the unmet need instead of fabricating a solution |
| Call is followed by a text | Context and the current plan are preserved |

**Metrics:** valid-assignment rate, constraint violations, stale-plan communication rate, successful clarification rate, handling of infeasible cases, latency, and scenario outcomes. State the denominator, dataset size, and test conditions. Separate planner quality from the agent's ability to gather and communicate information.

**Access correction:** the assumption that Chalk always requires private-cloud setup is too strong. Its documented quick-start describes managed environments with evaluation support. Actual access and runtime behavior still need testing; the first check should be a tiny end-to-end evaluation.

**Evidence to show:** the dataset, pinned configuration, scored results, a meaningful before/after comparison, and at least one inspected failure. Running the same demo script repeatedly is not a convincing benchmark.

**Stretch assessment:** low to moderate for evaluation; high for implementing overlapping Chalk and Daytona sandbox systems without a clear product reason.

**Keep or cut:** keep Chalk as the evaluation layer if it works promptly. If access is blocked, preserve the local benchmark for Overall and Sustainability, and drop the Chalk prize claim rather than pretending a custom results table is a Chalk integration.

**6. SpaceXAI — 4/10**

**Brutal assessment.** This is the weakest current fit. A disaster product does not become a strong space-data entry because a satellite image appears behind the map. There is a plausible path through Earth observation, but it must change the scenario and decisions.

**Published eligibility:** build with **Cursor** and use **Grok Imagine or the Grok Voice API** inside the product. The brief says greater Cursor use improves the chance of winning and offers bonus points for Grok Bot use in planning and collaboration. It strongly frames the challenge around real space data, although the explicit eligibility sentence names Cursor and the Grok APIs.

Each winning team member receives a branded Cursor mechanical keyboard; submissions also enter a raffle for a Cursor Owala bottle, according to the supplied brief.

**Essential improvements, only if this track remains in scope**

1. **Use a real Earth-observation input.** A preprocessed Copernicus emergency flood product is a plausible choice. Record the activation, acquisition time, geographic extent, and source.
2. **Connect the observation to a decision.** Use the observed flood extent to ground the affected area or scenario exposure. Explicitly distinguish observed extent from derived road restrictions and simulated future conditions.
3. **Do not overclaim satellite precision.** A flood mask does not establish indoor safety, exact water depth on every road, or minute-by-minute passability. Supplement uncertainty with human reports and labeled assumptions.
4. **Choose Grok Voice if it fits the existing experience.** A real voice interface is more natural here than decorative generated imagery. Prove the Photon-to-voice-provider path before committing the demo to it; compatibility is an implementation question, not an assumption.
5. **Document authentic Cursor use.** Explain the actual development workflow and useful contributions. Do not manufacture usage evidence or claim tools you did not use.

**Evidence to show:** identifiable space-derived data, the derived scenario inputs it influences, a working qualifying Grok API feature, and accurate Cursor documentation. A text-only Grok call does not satisfy the stated Imagine-or-Voice requirement.

Earth observation is a plausible thematic fit, not a guarantee of the sponsor's interpretation or preference. This track is worth pursuing only when these additions improve the product you already intend to build.

**Stretch assessment:** moderate with a ready-to-use flood dataset and working Grok Voice; high if it requires changing the disaster, location, interface, or data pipeline late in the build.

**Keep or cut:** keep optional satellite grounding and Grok Voice when they are already useful and stable. Cut the track if eligibility would require a separate feature branch or distract from the main demonstration.

**The architecture that keeps these tracks coherent**

| Component | Product responsibility | Prize contribution |
| --- | --- | --- |
| Shared state and resource ledger | Track people, facilities, hazards, reports, commitments, and plan versions | Overall; contextual data for Chalk |
| Conversation layer | Collect decision-changing information and communicate current assignments | Photon; optionally Grok Voice |
| Constrained allocator | Produce assignments that satisfy capacities, compatibility, routes, and priorities | Overall; credible Sustainability claims |
| Infrastructure and scenario simulator | Compute service continuity, intervention timing, and wastewater outcomes | Sustainability; execution workload for Daytona |
| Experiment runner | Compare isolated candidate plans and uncertainty cases | Daytona |
| Evaluation suite | Test reasoning, tool use, context handling, and communication against pinned cases | Chalk; evidence for Overall |
| Optional satellite input | Ground the scenario in an observed flood footprint | SpaceXAI; data credibility |

Agents may specialize in situation updates, household assistance, infrastructure interventions, and communication. They share one authoritative state and allocator. The number of agents is not the innovation.

The emergency planner reviews proposed actions. Offered resources remain provisional until confirmed. Every affected conversation should reference the current plan. When no feasible plan exists, show the unresolved need and limiting resource instead of producing a confident but invalid answer.

**The evidence package to build once and reuse across tracks**

- **Scenario specification:** location, observation sources, synthetic records, resource inventory, initial conditions, and assumptions.
- **Constraint specification:** capacity, availability, compatibility, crew qualifications, route access, task duration, deadlines, and reserve policy.
- **Fair baseline:** a reasonable incident-by-incident policy, compared under the same conditions and with the same available information.
- **Outcome table:** people reached before modeled hazard deadlines, unresolved urgent needs, service outage duration, modeled untreated discharge, conflicts, travel or fuel, and replanning time.
- **Evaluation cases:** held-out disruptions and conversation failures, with versioned results.
- **Inspectable trace:** what was reported, what changed, why the allocator changed assignments, what simulation computed, and who received an update.
- **Integration proof:** actual runtime use of each claimed sponsor tool, with a concise README pointing to relevant code.
- **Limitations:** identify which data is observed, reported, assumed, derived, or simulated. Report failures and uncertainty alongside improvements.

Do not invent improvement percentages before running the comparison. A smaller, explained result with reproducible assumptions is more defensible than a dramatic unsupported claim.

**Three-minute demo sequence**

| Time | Demonstration | What it proves |
| --- | --- | --- |
| 0:00–0:20 | Introduce one flooded district, competing needs, and limited resources | A clear user and consequential problem |
| 0:20–0:45 | Show the current allocation and threatened wastewater service | Resource constraints and the environmental mechanism |
| 0:45–1:25 | Live resident interaction adds an accessibility need or blocked pickup | Information gathering that changes the problem |
| 1:25–2:00 | Show a verified operator update, candidate evaluation, and revised assignments | Shared planning, infrastructure dependencies, and meaningful execution |
| 2:00–2:25 | Show updated resident communication and comparative outcomes | Personalization, consistency, and measured impact |
| 2:25–2:40 | Show one benchmark result or inspectable failure trace | Evidence beyond a scripted example |
| 2:40–3:00 | Explain ownership, integration, and learning | The teamwork criterion |

The operator interaction can be a clearly identified earlier live test if two calls would make the pitch unreliable. Do not present a recording or cached experiment as live. Prepare to demonstrate an additional judge-selected disruption during questions.

**Build priorities and cut rules**

1. **Complete the core loop:** shared state, constrained allocations, one environmental model, one conversation, one revised plan.
2. **Prove the result:** establish a reasonable baseline, test disruptions, label assumptions, and compute outcomes.
3. **Deepen Photon:** add confirmation, multi-party context, and useful follow-up messages.
4. **Integrate Chalk evaluations:** first prove one scored case, then expand the benchmark.
5. **Integrate Daytona experiments:** first prove one reproducible run, then add useful parallel evaluation and failure handling.
6. **Add SpaceXAI only if ready:** real satellite input and qualifying Grok functionality must support the existing product.

| Keep | Cut first when time is tight |
| --- | --- |
| One flood, one district, one complete cascade | Multiple disaster types and a whole-city operational model |
| Real shared state and assignment constraints | Cosmetic agent activity and many independent chatbots |
| Wastewater flow and storage model | Unsupported carbon accounting or additional environmental models |
| Clear map and visible resource movements | Photorealistic Treehouse interior and elaborate 3D rendering |
| One reliable phone experience | Many channels with incomplete behavior |
| Reproducible comparisons and a small benchmark | Broad dashboards with no evaluated decisions |
| Substantive sponsor integrations | Redundant sandboxes or features built solely for a prize |

Factory is intentionally outside this six-track plan. Adding another runtime agent framework would need a separate, compelling product justification.

**Final assessment:** EMBER can be a strong, focused entry when a judge can supply an unexpected fact, watch it change both an individual assistance assignment and an infrastructure intervention, and inspect why the resulting plan performs differently. The improvements that matter most are causal completeness, constrained decisions, believable environmental accounting, and a reliable human interaction. Sponsor breadth comes after those.

**Source and requirement notes**

This document consolidates the prior assessment and the supplied 2026 Devpost text; it is not a new eligibility ruling. Prize details are reproduced from that supplied text. Recommendations about competitiveness are our judgment, not official judging requirements. Product and API documentation establish capabilities, not proof that your accounts or integrations are working.

- [HackHarvard 2026 Devpost prizes](https://hackharvard2026.devpost.com/#prizes) — the user-supplied page text is the basis for eligibility, schedule, criteria, and awards.
- [HackHarvard official site](https://www.hhuh.io/) — event and sponsor context.
- [Photon 2.0 hackathon guidelines](https://somethingreat.notion.site/Hackathon-Guidelines-for-Photon-2-0-3f8e443f36bb81f9893fed0d08a4c01d) — supplementary category, experience, and channel guidance reviewed during the earlier research.
- [Photon 2.0 introduction](https://photon.codes/blog/introducing-photon-2.0) — messaging and voice platform context.
- [Daytona sandboxes](https://www.daytona.io/docs/en/sandboxes/) and [network limits](https://www.daytona.io/docs/en/network-limits/) — execution capabilities and operational limits.
- [Chalk evaluation quick-start](https://docs.chalk.ai/docs/evaluations/quick-start) and [evaluation concepts](https://docs.chalk.ai/docs/compute/evaluations) — setup, datasets, task versions, and scoring.
- [Grok Voice documentation](https://docs.x.ai/developers/model-capabilities/audio/voice) — qualifying voice API and integration capabilities.
- [Copernicus emergency data](https://emergency.copernicus.eu/data/) and [rapid mapping product downloads](https://mapping.emergency.copernicus.eu/about/rapid-mapping-manual/product-overview/how-is-a-product-delivered/viewing-and-downloading-a-product/) — possible satellite-derived scenario inputs.
- [EPA flood resilience guide for water and wastewater utilities](https://www.epa.gov/waterutilityresponse/flood-resilience-basic-guide-water-and-wastewater-utilities) — grounding for infrastructure vulnerability and environmental consequences.
- [IN-CORE interdependent network restoration](https://incore.ncsa.illinois.edu/doc/incore/analyses/indp.html) and [network cascading functionality](https://incore.ncsa.illinois.edu/doc/incore/analyses/nci_functionality.html) — existing work relevant to the novelty assessment.
