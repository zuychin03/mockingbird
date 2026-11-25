"""Job descriptions for the generation gate (V1.2_PLAN P3, D16): gold duties and offers.

The 40 descriptions of `tools/jd_fields.py`, plus six written for this gate where the bank's
vocabulary is thin: IT support, IT operations, customer support, a technical writer, a QA tester
and a research assistant. Each new one ends with what the employer offers, because the 40 have
almost no offers and "Learning budget of $1000" becoming a learning requirement (13/11) is the
failure D16 exists to stop. Written by Claude; no real employer is described.

`GOLD` lists each description's clear duties and offers, verbatim, in the text's order. A
sentence that is only context ("Words are part of the design.") is left out rather than forced
into a kind, so an item the model reads that matches nothing is not scored either way. The gate
reports, not gates, how the model's kinds agree with these (P3).

Adjudicated 25/11/2026 with the gate's labels (D6, activation item 10). Every kind stood;
it_ops moved from software to general.
"""

from __future__ import annotations

import jd_fields as jf

ADJUDICATED = True

D, O = "duty", "offer"

# (id, gold field, reason, text), as jd_fields.JDS
EXTRA = [
    ("it_support", "general", "IT help desk: no field of its own (1.2 Deferred), so general",
     """IT Support Officer

Join a 300-person logistics company as the first point of contact for IT. You will resolve
tickets from staff across three sites by phone, chat and in person, set up laptops and accounts
for new starters, and manage users and licences in Microsoft 365 and Active Directory. You will
troubleshoot printers, Wi-Fi and VPN problems, escalate what you cannot fix to our
infrastructure partner, and write clear how-to guides so staff can help themselves. You have a
year of help desk experience or a relevant qualification, and you explain technical things
patiently.

What we offer: a hybrid roster after probation, free on-site parking, and a $1,000 annual
learning budget for certifications."""),
    ("it_ops", "general", "runs servers, networks and backups rather than building software; "
     "moved from software to general (25/11)",
     """IT Operations Engineer

We run the servers, networks and backups behind a regional bank's branches. You will patch and
maintain Windows and Linux servers, monitor systems and respond to alerts, run and test our
backups and disaster recovery, and carry changes through our change advisory board. You will
automate routine work with PowerShell, take part in an after-hours on-call roster, and document
every system you touch. Three years in IT operations and solid networking fundamentals are
required.

We offer a 9-day fortnight, an on-call allowance and paid certification exams."""),
    ("customer_support", "general", "customer support: not building, analysing, designing or "
     "managing projects",
     """Customer Support Specialist

Our customers are small business owners who rely on our invoicing app to get paid. You will
answer questions by email and chat, troubleshoot account and billing problems, and walk
customers through features until they are confident on their own. You will log bugs for our
engineers with clear steps to reproduce, spot recurring problems and suggest fixes to the
product team, and keep our help centre articles up to date. You have at least a year in a
customer-facing role and you write clearly and warmly.

Perks include fully remote work, a home office allowance and two volunteer days a year."""),
    ("technical_writer", "general", "documentation: writing about software, not building it or "
     "designing its interface",
     """Technical Writer

Developers integrate with our payments platform through our API, and the documentation is often
the first thing they read. You will write and maintain API reference pages, integration guides
and release notes, interview engineers to understand new features before they ship, and test
every code sample you publish. You will review documentation written by engineers and set the
style everyone follows. Experience writing documentation for a software product and the ability
to read code are required.

You will join a friendly team of eight in our Sydney office, with flexible start times and an
annual conference allowance."""),
    ("qa_tester", "software", "tests software: the software field names testing",
     """QA Tester

Help us release our mobile ordering app without surprises. You will write and run test plans for
new features, carry out exploratory testing on iOS and Android, log defects with clear evidence
and verify fixes, and maintain our regression suite. You will work with developers during each
sprint to agree what done means, and help automate repetitive checks. Experience testing web or
mobile applications and a methodical eye for detail are essential; experience with Appium or
Cypress is a plus.

We are a fast-growing startup with a casual culture, free lunch on Fridays and stock options for
every employee."""),
    ("research_assistant", "general", "academic research support: data collection and reviews, "
     "not analysis for a business",
     """Research Assistant, Public Health

Join a university team studying how people in regional towns use telehealth. You will recruit
participants and run structured phone interviews, enter and clean survey data, search and
summarise published studies for literature reviews, and help prepare ethics applications and
reports. You will keep participant records confidential and follow the study protocol exactly. A
degree in health, social science or a related field and strong attention to detail are
required.

This is a two-year fixed-term role, 0.8 FTE, with salary packaging and generous leave."""),
]

GOLD: dict[str, list[tuple[str, str]]] = {
    "sw_backend": [
        ("build and run the services that move money for our merchants", D),
        ("design APIs in Python and Go", D),
        ("own services end to end from design to on-call", D),
        ("work with product to break down features into shippable pieces", D),
        ("You have shipped production services", D),
        ("are comfortable with PostgreSQL and message queues", D),
        ("you write tests as a matter of course", D)],
    "sw_frontend": [
        ("write React and TypeScript components", D),
        ("work closely with designers to turn their work into accessible, fast interfaces", D),
        ("review your colleagues' pull requests", D),
        ("two or more years of professional front-end development", D),
        ("a good grasp of browser performance", D),
        ("experience testing UI code", D)],
    "sw_sre": [
        ("keep our platform fast and available for two million users", D),
        ("automate infrastructure with Terraform", D),
        ("improve our monitoring and alerting", D),
        ("take part in a shared on-call rotation", D),
        ("lead blameless reviews after incidents", D),
        ("Strong Linux skills, experience with Kubernetes", D),
        ("the ability to write solid code in at least one language", D)],
    "sw_mobile": [
        ("help build our banking app, used by four hundred thousand customers each week", D),
        ("write Swift and SwiftUI", D),
        ("work with backend engineers on the APIs the app relies on", D),
        ("keep the app stable through careful testing and staged releases", D),
        ("Experience shipping apps to the App Store is required", D)],
    "sw_data_eng": [
        ("design and maintain batch and streaming pipelines in Spark and Airflow", D),
        ("model data in our lakehouse", D),
        ("make sure every job is tested, monitored and recoverable", D),
        ("You have built production data pipelines before", D),
        ("write clean Python and SQL", D),
        ("care about data quality and cost", D)],
    "sw_ml_eng": [
        ("take models from our research team and make them work in production", D),
        ("building training and serving pipelines", D),
        ("optimising inference latency", D),
        ("setting up monitoring for model drift", D),
        ("writing the services that put predictions in front of customers", D),
        ("Strong Python, experience with PyTorch and containerised deployment", D),
        ("a background in software engineering", D)],
    "sw_ux_eng": [
        ("build and maintain our component library in React", D),
        ("prototype new interactions in code so designers can test them with users", D),
        ("make sure what ships matches the design system", D),
        ("You are a strong front-end developer with an eye for interaction detail", D),
        ("comfortable reading Figma files and writing production TypeScript", D)],
    "sw_eng_manager": [
        ("lead a team of seven engineers who build our internal developer platform", D),
        ("hire and grow engineers", D),
        ("run one-on-ones and performance reviews", D),
        ("set technical direction with the team's staff engineer", D),
        ("make sure the team delivers on its commitments", D),
        ("You have been a software engineer yourself", D),
        ("have managed engineers for at least two years", D)],
    "da_analyst": [
        ("turn our product and sales data into answers the commercial team can act on", D),
        ("build and maintain dashboards", D),
        ("write SQL against our warehouse", D),
        ("present what you find to managers who do not read SQL", D),
        ("Experience designing and reading A/B tests is a plus", D),
        ("someone curious, careful with numbers and clear in writing", D)],
    "da_bi": [
        ("own reporting for our retail operations", D),
        ("gather reporting needs from store and regional managers", D),
        ("build and maintain Power BI reports", D),
        ("define the metrics everyone uses", D),
        ("investigate when the numbers move unexpectedly", D),
        ("Strong SQL and Power BI skills", D),
        ("experience working with non-technical stakeholders", D)],
    "da_marketing": [
        ("measure how our marketing spend turns into customers", D),
        ("analyse campaign performance across paid search, social and email", D),
        ("build attribution and forecasting models in spreadsheets and SQL", D),
        ("recommend where the next dollar should go", D),
        ("present a monthly review to the leadership team", D)],
    "da_scientist": [
        ("design and analyse experiments", D),
        ("build models of user retention and engagement", D),
        ("turn messy behavioural data into clear recommendations for product managers", D),
        ("fluent in SQL and Python or R", D),
        ("understand statistical inference", D),
        ("explain your findings simply", D)],
    "da_analytics_eng": [
        ("build the trusted data models that every analyst and dashboard in the company "
         "relies on", D),
        ("turn raw data into clean, documented, tested tables", D),
        ("define shared metrics with analysts and finance", D),
        ("teach analysts good practice", D),
        ("Experience with dbt, a cloud warehouse such as Snowflake or BigQuery, and version "
         "control", D)],
    "da_commercial": [
        ("analyse sales, margin and competitor pricing data", D),
        ("model the effect of promotions before they run", D),
        ("review how they performed afterwards", D),
        ("work in Excel and SQL", D),
        ("present your recommendations to category managers each week", D),
        ("Two years in an analytical role is preferred", D)],
    "da_supply": [
        ("help us keep the right stock in the right place", D),
        ("forecast demand by product and region", D),
        ("analyse supplier lead times and stock-outs", D),
        ("build the reports our planners use every morning", D),
        ("Strong Excel, SQL and some experience with forecasting methods", D),
        ("experience in retail or logistics is a plus", D)],
    "pm_core": [
        ("own the scheduling module of our workforce management product", D),
        ("talk to customers every week", D),
        ("decide what the team builds next and why", D),
        ("write clear problem statements for engineers and designers", D),
        ("measure whether what we shipped worked", D),
        ("Three or more years of product management in B2B software", D)],
    "pm_growth": [
        ("own our sign-up and onboarding experience and the numbers that come with it", D),
        ("find where new users drop off", D),
        ("decide which experiments to run", D),
        ("work with an engineer and a designer to ship them weekly", D),
        ("comfortable with funnel analytics and A/B testing", D),
        ("you have owned a product area before", D)],
    "pm_tpm": [
        ("decide what goes into the API and why", D),
        ("work with engineers on API design and deprecation", D),
        ("talk to the developers who build on us", D),
        ("A background in software engineering or a deep technical understanding of APIs", D)],
    "pm_owner": [
        ("own the product backlog for our online claims service", D),
        ("write user stories with clear acceptance criteria", D),
        ("prioritise the backlog with the business", D),
        ("keep stakeholders informed of what is coming", D),
        ("Experience as a product owner in an agile team", D),
        ("a certification such as CSPO", D)],
    "pm_senior": [
        ("Lead product for our consumer fitness app", D),
        ("set the vision and roadmap for the app", D),
        ("make the trade-offs between new features and retention work", D),
        ("run discovery with users", D),
        ("lead a team of engineers and designers to ship", D),
        ("five or more years of product management, including consumer mobile products", D)],
    "pm_associate": [
        ("Our APM programme is for people early in their product careers", O),
        ("support a senior product manager on our marketplace", D),
        ("run customer interviews", D),
        ("write requirements for small features", D),
        ("analyse how features perform after launch", D),
        ("gradually take ownership of a product area", D),
        ("A degree and some experience in a technical, analytical or customer-facing role", D)],
    "pm_head": [
        ("lead a team of four product managers", D),
        ("set product strategy for our accounting software for small businesses", D),
        ("own the product vision and roadmap", D),
        ("decide where we invest", D),
        ("coach your product managers", D),
        ("work with the CEO and the head of engineering on company priorities", D),
        ("Eight or more years in product, including leading product managers", D)],
    "ux_designer": [
        ("design how people book and manage appointments on our healthcare platform", D),
        ("map user journeys", D),
        ("sketch and prototype in Figma", D),
        ("test your designs with patients and clinicians", D),
        ("work with engineers until the design ships", D),
        ("A portfolio showing your process from research to final design", D)],
    "ux_researcher": [
        ("help our teams understand the people who use our banking products", D),
        ("plan and run interviews, usability tests and surveys", D),
        ("synthesise what you learn into clear insights", D),
        ("work with designers and product managers to act on them", D),
        ("Experience with a range of qualitative and quantitative research methods", D)],
    "ux_product_designer": [
        ("own design end to end for our team-collaboration app", D),
        ("run design critiques", D),
        ("build on our design system", D),
        ("prototype interactions and test them with customers", D),
        ("work that shows strong interaction and visual design, and how you made decisions", D)],
    "ux_ui": [
        ("shape how our travel booking site looks and feels", D),
        ("create high-fidelity interface designs", D),
        ("maintain and extend our design system's components, colours and type", D),
        ("make sure every screen meets accessibility standards", D),
        ("highly skilled in Figma", D),
        ("a portfolio of digital interface work", D)],
    "ux_content": [
        ("write and design the interface content for our insurance app", D),
        ("test content with users", D),
        ("build a content style guide", D),
        ("work alongside product designers from the first sketch", D),
        ("A portfolio of interface content work is required", D)],
    "ux_service": [
        ("redesign how residents apply for council permits, across the website, phone and "
         "service counters", D),
        ("map end-to-end journeys", D),
        ("run workshops with staff and residents", D),
        ("prototype new service models", D),
        ("work with digital and operations teams to deliver them", D),
        ("Experience with service design methods in the public sector", D)],
    "ux_lead": [
        ("lead UX for our e-commerce platform", D),
        ("mentor three designers", D),
        ("set design direction", D),
        ("review your team's work", D),
        ("run research with customers", D),
        ("make sure design has a voice in product decisions", D),
        ("at least six years of UX design experience, including leading projects and coaching "
         "other designers", D)],
    "pj_construction": [
        ("deliver office fit-out projects from handover to completion", D),
        ("plan and schedule the works", D),
        ("manage budgets and subcontractors", D),
        ("run site meetings", D),
        ("report progress to clients", D),
        ("make sure every project finishes safely, on time and on budget", D),
        ("Experience managing commercial construction projects", D)],
    "pj_it": [
        ("run the rollout of a new finance system across our twelve hospitals", D),
        ("build and maintain the project plan", D),
        ("manage risks, issues and dependencies", D),
        ("coordinate vendors and internal teams", D),
        ("report to the steering committee", D),
        ("PRINCE2 or PMP certification", D),
        ("experience delivering IT implementation projects", D)],
    "pj_tpm": [
        ("coordinate the delivery of our mobile and web releases across five engineering "
         "teams", D),
        ("track dependencies between teams", D),
        ("run release readiness reviews", D),
        ("remove blockers so the teams ship on schedule", D),
        ("make sure what is planned gets delivered", D),
        ("A technical background is helpful", D)],
    "pj_programme": [
        ("lead a programme of six projects moving our customer services online", D),
        ("set up governance", D),
        ("manage the programme budget and benefits", D),
        ("coordinate project managers", D),
        ("report to the executive sponsor", D),
        ("Experience leading large change programmes", D),
        ("managing senior stakeholders", D)],
    "pj_scrum": [
        ("help two agile teams deliver predictably", D),
        ("facilitate sprint planning, stand-ups, reviews and retrospectives", D),
        ("track and remove impediments", D),
        ("coach the teams and their stakeholders in scrum", D),
        ("report on delivery progress", D),
        ("at least two years as a scrum master", D)],
    "pj_coordinator": [
        ("help deliver conferences for corporate clients", D),
        ("keep project schedules and budgets up to date", D),
        ("book suppliers and venues", D),
        ("take minutes and chase actions", D),
        ("support the project managers on event days", D),
        ("someone organised, calm under pressure and keen to grow into project management", D)],
    "pj_implementation": [
        ("manage the onboarding of new enterprise customers onto our HR software", D),
        ("plan each implementation", D),
        ("agree timelines and responsibilities with the customer", D),
        ("coordinate our consultants and engineers", D),
        ("make sure each customer goes live on the agreed date", D),
        ("Experience managing customer-facing implementation projects", D)],
    "gen_nurse": [
        ("assess and care for patients before and after surgery", D),
        ("administer medications", D),
        ("work with doctors and allied health staff", D),
        ("support patients and families through their stay", D),
        ("Current registration with the nursing board", D),
        ("recent acute care experience", D)],
    "gen_sales": [
        ("sell our project management software to mid-sized businesses", D),
        ("manage the full sales cycle from first call to signed contract", D),
        ("run product demonstrations", D),
        ("build a pipeline of qualified opportunities", D),
        ("meet a quarterly revenue target", D),
        ("Two years of B2B software sales experience", D),
        ("a track record of exceeding quota", D)],
    "gen_retail": [
        ("Lead our flagship store and a team of twenty-five", D),
        ("manage rosters and labour costs", D),
        ("recruit and train staff", D),
        ("keep stock levels and visual merchandising to standard", D),
        ("deliver great customer service every day", D),
        ("At least three years of retail management experience", D)],
    "gen_accountant": [
        ("look after month-end close for our group of companies", D),
        ("prepare journals and reconciliations", D),
        ("manage accounts payable and receivable", D),
        ("prepare management accounts", D),
        ("support the annual audit and tax returns", D),
        ("A CPA or CA qualification, or progress towards one", D),
        ("strong Excel skills", D)],
    "it_support": [
        ("resolve tickets from staff across three sites by phone, chat and in person", D),
        ("set up laptops and accounts for new starters", D),
        ("manage users and licences in Microsoft 365 and Active Directory", D),
        ("troubleshoot printers, Wi-Fi and VPN problems", D),
        ("escalate what you cannot fix to our infrastructure partner", D),
        ("write clear how-to guides so staff can help themselves", D),
        ("a year of help desk experience or a relevant qualification", D),
        ("you explain technical things patiently", D),
        ("a hybrid roster after probation", O),
        ("free on-site parking", O),
        ("a $1,000 annual learning budget for certifications", O)],
    "it_ops": [
        ("patch and maintain Windows and Linux servers", D),
        ("monitor systems and respond to alerts", D),
        ("run and test our backups and disaster recovery", D),
        ("carry changes through our change advisory board", D),
        ("automate routine work with PowerShell", D),
        ("take part in an after-hours on-call roster", D),
        ("document every system you touch", D),
        ("Three years in IT operations and solid networking fundamentals", D),
        ("We offer a 9-day fortnight, an on-call allowance and paid certification exams", O)],
    "customer_support": [
        ("answer questions by email and chat", D),
        ("troubleshoot account and billing problems", D),
        ("walk customers through features until they are confident on their own", D),
        ("log bugs for our engineers with clear steps to reproduce", D),
        ("spot recurring problems and suggest fixes to the product team", D),
        ("keep our help centre articles up to date", D),
        ("at least a year in a customer-facing role", D),
        ("you write clearly and warmly", D),
        ("Perks include fully remote work, a home office allowance and two volunteer days a "
         "year", O)],
    "technical_writer": [
        ("write and maintain API reference pages, integration guides and release notes", D),
        ("interview engineers to understand new features before they ship", D),
        ("test every code sample you publish", D),
        ("review documentation written by engineers", D),
        ("set the style everyone follows", D),
        ("Experience writing documentation for a software product", D),
        ("the ability to read code", D),
        ("a friendly team of eight in our Sydney office, with flexible start times and an "
         "annual conference allowance", O)],
    "qa_tester": [
        ("write and run test plans for new features", D),
        ("carry out exploratory testing on iOS and Android", D),
        ("log defects with clear evidence and verify fixes", D),
        ("maintain our regression suite", D),
        ("work with developers during each sprint to agree what done means", D),
        ("help automate repetitive checks", D),
        ("Experience testing web or mobile applications and a methodical eye for detail", D),
        ("experience with Appium or Cypress is a plus", D),
        ("We are a fast-growing startup with a casual culture, free lunch on Fridays and stock "
         "options for every employee", O)],
    "research_assistant": [
        ("recruit participants and run structured phone interviews", D),
        ("enter and clean survey data", D),
        ("search and summarise published studies for literature reviews", D),
        ("help prepare ethics applications and reports", D),
        ("keep participant records confidential", D),
        ("follow the study protocol exactly", D),
        ("A degree in health, social science or a related field and strong attention to "
         "detail", D),
        ("This is a two-year fixed-term role, 0.8 FTE, with salary packaging and generous "
         "leave", O)],
}


def descriptions() -> list[tuple[str, str, str, str]]:
    """(id, gold field, reason, text) for every description the gate runs."""
    return list(jf.JDS) + EXTRA
