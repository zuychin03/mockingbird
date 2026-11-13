"""Turn fixtures for the 1.2 fields (V1.2_PLAN P1): 15 answers per field, 75 in all.

Written by Claude and adjudicated by Duy (D6) before the gate scores against them. Like
`fixtures_v2.py` they are hand-written, so they suit a paired comparison of prompt arms better
than an absolute claim; unlike it, every label carries its reason so it can be overruled.

The five questions per field are drafts that seed P2's bank review, not approved bank text.

Families per field, mirroring the software set: five complete answers (the fourth short but
complete); four probes (no outcome, team credit only, situation only, a figure with no method);
two reasks (a blank, off topic); one clarify, one skip, one end; and one "can't think of one"
worded near "rather not", the confusion `contract.SYSTEM` names.
"""

# Flipped by hand once Duy has adjudicated every label below. The gate refuses to score the
# new fields against unadjudicated labels unless told the run is provisional.
# Adjudicated by Duy 11/11/2026, no labels overruled.
ADJUDICATED = True

QUESTIONS = {
    "data_analytics": [
        "Tell me about an analysis you did that changed a decision someone was about to make.",
        "Describe a time the data you were given turned out to be wrong or incomplete.",
        "Tell me about a dashboard or report you built. How did you know people used it?",
        "Walk me through an experiment or A/B test you analysed, and what you concluded.",
        "Tell me about a time you explained a finding to people without a data background.",
    ],
    "product_management": [
        "Tell me about a feature you decided not to build, and how you made that call.",
        "Describe a launch that didn't go the way you planned.",
        "Tell me about a time two stakeholders wanted different things from your roadmap.",
        "Walk me through how customer research changed a product decision you'd made.",
        "Tell me about a metric you set for a product, and how it moved.",
    ],
    "ux_design": [
        "Tell me about a design decision you changed after usability testing.",
        "Describe a time you had to defend a design to a stakeholder who disagreed.",
        "Tell me about a project where you had very little user research to work from.",
        "Walk me through how you made something you designed more accessible.",
        "Tell me about a time an engineering constraint forced you to change a design.",
    ],
    "project_management": [
        "Tell me about a project that was slipping, and how you brought it back.",
        "Describe a time you had to manage scope creep.",
        "Tell me about a risk you spotted early, and what you did about it.",
        "Tell me about a time you had to deliver bad news to a sponsor or client.",
        "Describe how you got people who didn't report to you to deliver on time.",
    ],
    "general": [
        "Tell me about a time you had to meet a tight deadline.",
        "Describe a mistake you made at work, and what you did about it.",
        "Tell me about a time you worked with someone you found difficult.",
        "Tell me about a time you took on something outside your usual responsibilities.",
        "Describe a time you changed how something was done at work.",
    ],
}

# (field, question_index, gold, answer, reason)
FIXTURES = [
    # ---------------------------------------------------------------- data analytics
    ("data_analytics", 0, "advance",
     "Our marketing lead wanted to cut the email programme because last-click attribution gave "
     "it almost nothing. I pulled twelve months of orders and compared customers in the weeks "
     "emails were paused by an outage against the weeks they ran. Customers who got emails "
     "reordered about eighteen percent more within sixty days. I presented that with the "
     "caveats, and they kept the programme and moved budget out of paid social instead.",
     "situation, own analysis and the decision it changed"),
    ("data_analytics", 0, "probe",
     "Finance was about to raise prices on our basic plan, so I looked at churn by plan and "
     "tenure and modelled who would leave at the new price. I sent my analysis to the pricing "
     "committee the week before they met.",
     "no outcome: we never hear whether the decision changed"),
    ("data_analytics", 0, "clarify",
     "When you say changed a decision, do you mean one I was asked to inform, or one I pushed "
     "back on without being asked?",
     "asks which meaning of the question to answer"),
    ("data_analytics", 1, "advance",
     "I was building a weekly revenue report and the totals came out about six percent higher "
     "than finance's numbers. I traced it to refunds being loaded a day late, so some weeks "
     "counted the sale but not the refund. I wrote a check that compared our totals with the "
     "ledger every morning and flagged the load order to data engineering, who fixed it. Our "
     "report has matched finance to the cent since.",
     "situation, own investigation and fix, lasting result"),
    ("data_analytics", 1, "probe",
     "We found the CRM export was missing about a third of the leads. We went back to the "
     "source system, we rebuilt the extract, and we got the numbers right before the quarterly "
     "review.",
     "team credit only: nothing they did themselves"),
    ("data_analytics", 1, "skip",
     "I'd rather not go into that one, it involves a client I can't talk about. Can we do the "
     "next one?",
     "could answer, declines this question"),
    ("data_analytics", 2, "advance",
     "I built a stock-availability dashboard for our store managers after they told me they "
     "were phoning the warehouse every morning. I kept it to one page with the five items each "
     "store was most likely to run out of. I checked the usage logs after a month: forty of our "
     "fifty-two managers opened it most days, and calls to the warehouse dropped by about half.",
     "situation, own build, and how they knew it was used"),
    ("data_analytics", 2, "probe",
     "Our sales team had no single view of their pipeline. Everything lived in different "
     "spreadsheets owned by different regional managers.",
     "situation only: no action, no outcome"),
    ("data_analytics", 2, "reask",
     "Hmm, I'm drawing a blank on that one, sorry.",
     "a blank: no answer produced, still willing"),
    ("data_analytics", 3, "advance",
     "I analysed our free-shipping test. I checked the groups were balanced, compared average "
     "order value over three weeks, and found the lift didn't cover the shipping cost, so we "
     "didn't roll it out.",
     "short but complete: the test, own analysis, the conclusion"),
    ("data_analytics", 3, "probe",
     "The new onboarding flow lifted activation by eleven percent.",
     "a figure with no method: how they analysed it is missing"),
    ("data_analytics", 3, "end",
     "Sorry, I'm going to have to stop the interview here, something's come up at work.",
     "asks to stop the whole interview"),
    ("data_analytics", 4, "advance",
     "I found that our delivery delays mostly came from one carrier in two regions. The "
     "operations managers didn't want regression output, so I showed them one map with the "
     "late deliveries in red and one sentence: one carrier, two regions, sixty percent of the "
     "delays. I left the detail in an appendix. They renegotiated with that carrier the next "
     "month, and late deliveries fell by a third over the quarter.",
     "situation, how they explained it, what happened"),
    ("data_analytics", 4, "reask",
     "I think being a good communicator is mostly about being a good listener, and I've always "
     "been a people person.",
     "off topic: a trait, no example"),
    ("data_analytics", 4, "reask",
     "I'd rather not make one up. I honestly can't remember presenting to anyone outside the "
     "data team.",
     "cannot recall one; 'rather not make one up' is honesty, not a refusal"),

    # ---------------------------------------------------------------- product management
    ("product_management", 0, "advance",
     "Sales wanted a custom reporting builder because two big prospects had asked for it. I "
     "interviewed both prospects and eight existing customers and found what they needed was a "
     "scheduled export to their own BI tool. I said no to the builder, we shipped the export in "
     "three weeks instead of the quarter the builder would have taken, and both prospects "
     "signed.",
     "situation, own call and how it was made, outcome"),
    ("product_management", 0, "probe",
     "I decided not to build offline mode for our field app. I looked at usage data, saw that "
     "almost everyone had signal when they used it, and wrote up the reasoning for the "
     "leadership team.",
     "no outcome: what happened after the call is missing"),
    ("product_management", 0, "clarify",
     "Do you mean something I killed before it started, or something we stopped halfway "
     "through?",
     "asks which meaning of the question to answer"),
    ("product_management", 1, "advance",
     "We launched a redesigned checkout and conversion dropped four percent in the first week. "
     "I'd skipped a staged rollout because of a marketing deadline. I rolled it back to half of "
     "traffic, watched session recordings, and found the new address form was rejecting valid "
     "postcodes. Once that was fixed, conversion came back above the old flow, and I haven't "
     "skipped a staged rollout since.",
     "situation, own response, outcome and lesson"),
    ("product_management", 1, "probe",
     "Our team launched a loyalty programme that nobody signed up for. We looked at the "
     "funnel, we redid the onboarding, and we got sign-ups to about twenty percent within two "
     "months.",
     "team credit only: nothing they did themselves"),
    ("product_management", 1, "skip",
     "That one's still a bit raw, I'd prefer to skip it if that's okay.",
     "could answer, declines this question"),
    ("product_management", 2, "advance",
     "Our head of sales wanted enterprise permissions next and our support lead wanted the "
     "billing bugs fixed, since they drove most tickets. I put both on one page: revenue at risk "
     "in three enterprise deals against the hours support spent on billing. Billing was costing "
     "more, so I scheduled it first and gave sales a committed date for permissions. Tickets "
     "fell by thirty percent, and permissions shipped on the date I gave.",
     "situation, how they decided, outcome for both sides"),
    ("product_management", 2, "probe",
     "At my last company marketing wanted a referral programme and the engineering lead wanted "
     "to spend the quarter on technical debt.",
     "situation only: no action, no outcome"),
    ("product_management", 2, "reask",
     "Nothing's coming to mind, sorry. I can't think of one.",
     "a blank: no answer produced, still willing"),
    ("product_management", 3, "advance",
     "I'd planned a mobile app for our bookings product. Ten customer interviews showed people "
     "booked from work laptops, so I cancelled the app and improved the desktop flow instead. "
     "Bookings rose twelve percent.",
     "short but complete: the plan, the research, the change and result"),
    ("product_management", 3, "probe",
     "Research changed our pricing page, and sign-ups went up fifteen percent.",
     "a figure with no method: what research, and what they did, is missing"),
    ("product_management", 3, "end",
     "I'm really sorry, I have to end the interview now.",
     "asks to stop the whole interview"),
    ("product_management", 4, "advance",
     "For our team-scheduling product I set weekly active teams as the main metric, because "
     "sign-ups were growing while most teams went quiet after a week. I added a setup checklist "
     "and a reminder to the team admin on day three. Weekly active teams went from about "
     "thirty-five to fifty percent of new sign-ups over two quarters, and I reported it monthly "
     "to leadership.",
     "the metric, why, what they did, how it moved"),
    ("product_management", 4, "reask",
     "Metrics matter, but honestly I think the best product managers just have great "
     "intuition about what users want.",
     "off topic: an opinion, no example"),
    ("product_management", 4, "reask",
     "I'd love to answer this but I can't think of a metric I set myself. I've always "
     "inherited them.",
     "cannot think of one, and says they would answer"),

    # ---------------------------------------------------------------- UX design
    ("ux_design", 0, "advance",
     "I designed a sign-up flow that put every field on one long page, because I thought fewer "
     "steps would feel faster. In testing with six participants, four stalled at the payment "
     "section and two gave up. I split it into three short steps with a progress bar and "
     "retested: all six finished, and in production completion rose from fifty-eight to "
     "seventy-one percent.",
     "the decision, what testing showed, the change and result"),
    ("ux_design", 0, "probe",
     "In testing, people couldn't find the filters on our search page, so I moved them from a "
     "side panel into a bar above the results and ran another round of sessions.",
     "no outcome: the second round's result is missing"),
    ("ux_design", 0, "clarify",
     "By usability testing, do you mean moderated sessions, or would analytics and A/B tests "
     "count too?",
     "asks which meaning of the question to answer"),
    ("ux_design", 1, "advance",
     "Our sales director wanted the pricing page to lead with the enterprise plan. I thought it "
     "would scare off the small teams who were most of our sign-ups. Rather than argue taste, I "
     "showed him recordings of five small-business users hesitating on the enterprise price and "
     "proposed a test. We ran both for two weeks; mine had twenty percent more trial starts and "
     "the same enterprise enquiries, so he agreed to keep it.",
     "the disagreement, how they defended it, outcome"),
    ("ux_design", 1, "probe",
     "The product owner didn't like our new navigation. We walked him through the research, we "
     "showed him the prototype, and in the end we got it approved.",
     "team credit only: nothing they did themselves"),
    ("ux_design", 1, "skip",
     "I'd rather skip that one, the person involved still works with me.",
     "could answer, declines this question"),
    ("ux_design", 2, "advance",
     "I joined a startup that wanted an invoicing tool and had no research budget. I spent two "
     "days calling five of the founders' existing customers and watched three of them send an "
     "invoice with their current tool over a screen share. That showed chasing late payments "
     "mattered more than creating invoices, so I designed around reminders first. After launch, "
     "reminders were the feature customers mentioned most when they renewed.",
     "situation, own improvised research, outcome"),
    ("ux_design", 2, "probe",
     "At an agency we were asked to redesign a council's website with two weeks and no access "
     "to any of its residents.",
     "situation only: no action, no outcome"),
    ("ux_design", 2, "reask",
     "Hmm. I've always had research to work from, so nothing comes to mind.",
     "a blank: no example to give, still willing"),
    ("ux_design", 3, "advance",
     "Our form errors were shown only in red. I added text and an icon to every error and fixed "
     "the focus order, and screen-reader users in our next test completed the form for the "
     "first time.",
     "short but complete: the problem, own fix, result"),
    ("ux_design", 3, "probe",
     "I got our app's accessibility score from sixty-two to ninety-four.",
     "a figure with no method: what they changed is missing"),
    ("ux_design", 3, "end",
     "Can we stop here? I need to end the interview, sorry.",
     "asks to stop the whole interview"),
    ("ux_design", 4, "advance",
     "I designed a live order tracker with a moving map. The engineers told me the location "
     "feed only refreshed every two minutes, so the map would jump and look broken. I reworked "
     "it into a timeline of stages with an estimated arrival time, and showed the map only in "
     "the last ten minutes, when the feed was faster. It shipped on time, and 'where is my "
     "order' calls fell by about a quarter.",
     "the constraint, own redesign, outcome"),
    ("ux_design", 4, "reask",
     "I love working closely with engineers. Honestly, some of my best friends are developers.",
     "off topic: no example"),
    ("ux_design", 4, "reask",
     "Not skipping it, I just can't recall a time a constraint changed one of my designs.",
     "cannot recall one, and says it is not a refusal"),

    # ---------------------------------------------------------------- project management
    ("project_management", 0, "advance",
     "A warehouse system rollout I ran was three weeks behind with six weeks to go, mostly "
     "because data migration and training were waiting on each other. I split the cut-over "
     "into two sites instead of four, moved two trainers onto the data clean-up, and held a "
     "fifteen-minute check-in every morning. The first two sites went live on the original "
     "date, and the other two followed three weeks later without overtime.",
     "situation, own recovery plan, outcome"),
    ("project_management", 0, "probe",
     "Our office move was falling behind because the fit-out contractor kept missing dates. I "
     "rebuilt the schedule around their real capacity and set up a weekly call with their site "
     "manager.",
     "no outcome: whether it came back is missing"),
    ("project_management", 0, "clarify",
     "Slipping on time, or on budget? They were quite different stories for me.",
     "asks which meaning of the question to answer"),
    ("project_management", 1, "advance",
     "On a CRM rollout the sales team kept adding reports they wanted at launch, and we'd gone "
     "from twelve to thirty. I set up a change log where every request needed an owner and a "
     "reason, and took the list to the sponsor with the cost of each in days. She cut it back "
     "to fifteen for launch and parked the rest for phase two. We launched on the planned date.",
     "situation, own control, outcome"),
    ("project_management", 1, "probe",
     "Scope kept growing on our website project. We set up a change board, we agreed priorities "
     "with the client, and we delivered on time.",
     "team credit only: nothing they did themselves"),
    ("project_management", 1, "skip",
     "Pass on that one, please.",
     "declines this question"),
    ("project_management", 2, "advance",
     "Planning a data-centre move, I noticed our only network engineer was booked on another "
     "project in the week of the cut-over. I raised it at the risk review, got the other "
     "project to move its work by a week, and lined up a contractor as a backup. The cut-over "
     "finished in one night with no outage, and the backup cost nothing because we didn't need "
     "him.",
     "the risk, own response, outcome"),
    ("project_management", 2, "probe",
     "We were about to start a system upgrade and the vendor was going through an acquisition "
     "at the same time.",
     "situation only: no action, no outcome"),
    ("project_management", 2, "reask",
     "Sorry, I can't think of one right now.",
     "a blank: no answer produced, still willing"),
    ("project_management", 3, "advance",
     "I told our sponsor the launch would slip a month because testing found a payroll error. "
     "I brought the fix plan and two date options, she picked one, and we hit it.",
     "short but complete: the news, how they delivered it, outcome"),
    ("project_management", 3, "probe",
     "I had to tell a client their project was going to cost about forty thousand dollars more.",
     "a figure with no method: how they told them, and what happened, is missing"),
    ("project_management", 3, "end",
     "I'm going to have to stop the interview here, sorry, I've been called away.",
     "asks to stop the whole interview"),
    ("project_management", 4, "advance",
     "On a compliance project I needed reports from five department heads, none of whom "
     "reported to me. I met each of them to find out what would make it easier, gave each a "
     "template that took about an hour, and set a deadline two weeks before mine. I sent their "
     "managers a weekly one-line status naming who was done. Four were in on time, the fifth a "
     "day late, and we submitted to the regulator early.",
     "situation, own approach, outcome"),
    ("project_management", 4, "reask",
     "Influence without authority is so important. I think it comes down to trust and building "
     "relationships over time.",
     "off topic: an opinion, no example"),
    ("project_management", 4, "reask",
     "I'd rather not pretend. I've never had people outside my team deliver for me, so I can't "
     "think of an example.",
     "cannot think of one; 'rather not pretend' is honesty, not a refusal"),

    # ---------------------------------------------------------------- general
    ("general", 0, "advance",
     "Two days before a trade show, our printer told us the banners and brochures would be a "
     "week late. I was the marketing coordinator, so I rang three local printers, found one "
     "that could do it overnight if we sent final files by noon, and got the designer to sign "
     "off the files that morning. Everything arrived the evening before the show, for about ten "
     "percent more than the original quote.",
     "situation, own action, outcome"),
    ("general", 0, "probe",
     "At the restaurant I managed we had a hundred-person function booked with a day's notice. "
     "I redid the rota, called in two extra staff and prepped the menu with the chef that "
     "night.",
     "no outcome: how the function went is missing"),
    ("general", 0, "clarify",
     "What do you mean by tight? Like hours, or a few days?",
     "asks what the question means"),
    ("general", 1, "advance",
     "As a payroll officer I entered the wrong tax code for a new starter, and she was overpaid "
     "for two months. When I spotted it, I told my manager the same day, worked out the exact "
     "amount, and sat down with her to agree a repayment over three pay cycles rather than all "
     "at once. I then added a second check on every new starter's set-up, and it hasn't "
     "happened again.",
     "the mistake, own response, outcome"),
    ("general", 1, "probe",
     "Our team sent a customer the wrong order twice in a row. We apologised, we sent the right "
     "stock by courier, and we kept the account.",
     "team credit only: nothing they did themselves"),
    ("general", 1, "skip",
     "I'd rather not answer that one, if that's alright.",
     "declines this question"),
    ("general", 2, "advance",
     "A colleague on the front desk kept leaving the end-of-day cash count to me, and I was "
     "staying forty minutes late. Instead of going to the manager, I asked her about it, and "
     "she said she didn't trust herself with the till software. I showed her how it worked over "
     "two quiet afternoons and we agreed to alternate days. After that I left on time, and she "
     "started doing the count on her own.",
     "situation, own approach, outcome"),
    ("general", 2, "probe",
     "I worked on a team where one person would always talk over everyone in meetings.",
     "situation only: no action, no outcome"),
    ("general", 2, "reask",
     "Um, no, I've been lucky. I've always got on with people, so nothing comes to mind.",
     "a blank: no example, still willing"),
    ("general", 3, "advance",
     "When our office manager left, I took over ordering supplies. I set up a shared request "
     "list and one monthly order, and we cut supply spending by about fifteen percent.",
     "short but complete: situation, own change, result"),
    ("general", 3, "probe",
     "I ended up running the stockroom for six months on top of my normal job.",
     "a figure with no method: what they did, and how it went, is missing"),
    ("general", 3, "end",
     "Sorry, I need to stop here. I can't continue the interview today.",
     "asks to stop the whole interview"),
    ("general", 4, "advance",
     "At the clinic where I worked reception, patients were waiting on hold for up to twenty "
     "minutes to book. I suggested an online booking form and a call-back option, and trialled "
     "them for a month on one doctor's appointments. Hold times on that line halved, so the "
     "practice manager rolled it out to all six doctors.",
     "situation, own change, outcome"),
    ("general", 4, "reask",
     "I'm someone who's always looking to improve things. I think that's just my personality.",
     "off topic: a trait, no example"),
    ("general", 4, "reask",
     "I don't want to pass on it, but nothing comes to mind, sorry.",
     "cannot think of one, and says it is not a refusal"),
]
