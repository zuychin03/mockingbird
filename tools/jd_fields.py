"""Job descriptions for the field-detection gate (V1.2_PLAN P1): 40, gold field and reason each.

Written for the purpose by Claude; no real employer is described. Adjudicated by Duy (D6)
before the gate scores against them. Eight are software, seven each are the four new fields,
and four are general: the plan's "eight per new field" left no room for the general cases it
names, so the total and the 36-of-40 pass mark were kept and the split moved.

The hard ones sit on a boundary on purpose: data engineer, ML engineer, UX engineer and
engineering manager (software); analytics engineer and data scientist (data analytics);
growth and technical product managers (product); content and service designers (UX);
technical project manager and scrum master (project); and a nurse, a salesperson and an
accountant (general). `planner.FIELD_SYSTEM`'s field definitions and these labels share an
author, so adjudicating a boundary label is also adjudicating the definition.
"""

# Adjudicated by Duy 11/11/2026, no labels overruled.
ADJUDICATED = True

# (id, gold, reason, text)
JDS = [
    # ---------------------------------------------------------------- software
    ("sw_backend", "software", "builds and runs backend services",
     """Backend Engineer, Payments

We are hiring a backend engineer to build and run the services that move money for our
merchants. You will design APIs in Python and Go, own services end to end from design to
on-call, and work with product to break down features into shippable pieces. You have shipped
production services, are comfortable with PostgreSQL and message queues, and you write tests
as a matter of course."""),
    ("sw_frontend", "software", "writes production front-end code",
     """Frontend Developer (React)

Join the team that builds our customer portal. You will write React and TypeScript
components, work closely with designers to turn their work into accessible, fast interfaces,
and review your colleagues' pull requests. We are looking for two or more years of
professional front-end development, a good grasp of browser performance, and experience
testing UI code."""),
    ("sw_sre", "software", "keeps production systems running through code and automation",
     """Site Reliability Engineer

You will keep our platform fast and available for two million users. Day to day you will
automate infrastructure with Terraform, improve our monitoring and alerting, take part in a
shared on-call rotation, and lead blameless reviews after incidents. Strong Linux skills,
experience with Kubernetes, and the ability to write solid code in at least one language
are essential."""),
    ("sw_mobile", "software", "builds a mobile app",
     """iOS Engineer

We are looking for an iOS engineer to help build our banking app, used by four hundred
thousand customers each week. You will write Swift and SwiftUI, work with backend engineers
on the APIs the app relies on, and keep the app stable through careful testing and staged
releases. Experience shipping apps to the App Store is required."""),
    ("sw_data_eng", "software", "builds data pipelines: the work is engineering, not analysis",
     """Data Engineer

Our analysts and data scientists depend on the pipelines you will build. You will design and
maintain batch and streaming pipelines in Spark and Airflow, model data in our lakehouse, and
make sure every job is tested, monitored and recoverable. You have built production data
pipelines before, write clean Python and SQL, and care about data quality and cost."""),
    ("sw_ml_eng", "software", "deploys and serves models: engineering work",
     """Machine Learning Engineer

You will take models from our research team and make them work in production. That means
building training and serving pipelines, optimising inference latency, setting up monitoring
for model drift, and writing the services that put predictions in front of customers. Strong
Python, experience with PyTorch and containerised deployment, and a background in software
engineering are required."""),
    ("sw_ux_eng", "software", "writes production UI code and a component library, not design",
     """UX Engineer

Sitting between design and engineering, you will build and maintain our component library in
React, prototype new interactions in code so designers can test them with users, and make
sure what ships matches the design system. You are a strong front-end developer with an eye
for interaction detail, and you are comfortable reading Figma files and writing production
TypeScript."""),
    ("sw_eng_manager", "software", "manages an engineering team",
     """Engineering Manager, Platform

You will lead a team of seven engineers who build our internal developer platform. You will
hire and grow engineers, run one-on-ones and performance reviews, set technical direction
with the team's staff engineer, and make sure the team delivers on its commitments. You have
been a software engineer yourself and have managed engineers for at least two years."""),

    # ---------------------------------------------------------------- data analytics
    ("da_analyst", "data_analytics", "turns data into answers for the business",
     """Data Analyst, Customer Insights

You will turn our product and sales data into answers the commercial team can act on. Most
weeks you will build and maintain dashboards, write SQL against our warehouse, and present
what you find to managers who do not read SQL. Experience designing and reading A/B tests is a
plus. We are looking for someone curious, careful with numbers and clear in writing."""),
    ("da_bi", "data_analytics", "business intelligence reporting",
     """Business Intelligence Analyst

We need a BI analyst to own reporting for our retail operations. You will gather reporting
needs from store and regional managers, build and maintain Power BI reports, define the
metrics everyone uses, and investigate when the numbers move unexpectedly. Strong SQL and
Power BI skills and experience working with non-technical stakeholders are essential."""),
    ("da_marketing", "data_analytics", "analyses campaign performance",
     """Marketing Analyst

You will measure how our marketing spend turns into customers. You will analyse campaign
performance across paid search, social and email, build attribution and forecasting models
in spreadsheets and SQL, and recommend where the next dollar should go. You will report to
the head of marketing and present a monthly review to the leadership team."""),
    ("da_scientist", "data_analytics", "a data scientist whose work is analysis and experiments",
     """Data Scientist, Product Analytics

Help our product teams decide what to build by finding out what is actually working. You
will design and analyse experiments, build models of user retention and engagement, and turn
messy behavioural data into clear recommendations for product managers. You are fluent in
SQL and Python or R, understand statistical inference, and explain your findings simply."""),
    ("da_analytics_eng", "data_analytics", "models data for analysts; the work serves analysis",
     """Analytics Engineer

You will build the trusted data models that every analyst and dashboard in the company relies
on. Using dbt and SQL, you will turn raw data into clean, documented, tested tables, define
shared metrics with analysts and finance, and teach analysts good practice. Experience with
dbt, a cloud warehouse such as Snowflake or BigQuery, and version control is required."""),
    ("da_commercial", "data_analytics", "pricing and commercial analysis from data",
     """Commercial Analyst

Our commercial team needs an analyst to sharpen pricing and promotions. You will analyse
sales, margin and competitor pricing data, model the effect of promotions before they run,
and review how they performed afterwards. You will work in Excel and SQL and present your
recommendations to category managers each week. Two years in an analytical role is
preferred."""),
    ("da_supply", "data_analytics", "demand forecasting and supply analysis",
     """Supply Chain Analyst

You will help us keep the right stock in the right place. You will forecast demand by
product and region, analyse supplier lead times and stock-outs, and build the reports our
planners use every morning. Strong Excel, SQL and some experience with forecasting methods
are required; experience in retail or logistics is a plus."""),

    # ---------------------------------------------------------------- product management
    ("pm_core", "product_management", "decides what a B2B product does and why",
     """Product Manager

You will own the scheduling module of our workforce management product, used by eight
hundred businesses. You will talk to customers every week, decide what the team builds next
and why, write clear problem statements for engineers and designers, and measure whether what
we shipped worked. Three or more years of product management in B2B software is
preferred."""),
    ("pm_growth", "product_management", "a product manager whose levers are experiments",
     """Growth Product Manager

You will own our sign-up and onboarding experience and the numbers that come with it. You
will find where new users drop off, decide which experiments to run, work with an engineer
and a designer to ship them weekly, and decide what to keep. You are comfortable with funnel
analytics and A/B testing, and you have owned a product area before."""),
    ("pm_tpm", "product_management", "a technical PM: still decides what the product does",
     """Technical Product Manager, Developer Platform

Our customers are developers, and our product is our public API. You will decide what goes
into the API and why, work with engineers on API design and deprecation, write
specifications, and talk to the developers who build on us. A background in software
engineering or a deep technical understanding of APIs is required."""),
    ("pm_owner", "product_management", "owns a product backlog and its priorities",
     """Product Owner

Working in a scrum team of six, you will own the product backlog for our online claims
service. You will write user stories with clear acceptance criteria, prioritise the backlog
with the business, accept completed work, and keep stakeholders informed of what is coming.
Experience as a product owner in an agile team and a certification such as CSPO are
preferred."""),
    ("pm_senior", "product_management", "product strategy and roadmap for a consumer app",
     """Senior Product Manager, Mobile

Lead product for our consumer fitness app. You will set the vision and roadmap for the app,
make the trade-offs between new features and retention work, run discovery with users, and
lead a team of engineers and designers to ship. You have five or more years of product
management, including consumer mobile products."""),
    ("pm_associate", "product_management", "a junior product manager",
     """Associate Product Manager

Our APM programme is for people early in their product careers. You will support a senior
product manager on our marketplace, run customer interviews, write requirements for small
features, analyse how features perform after launch, and gradually take ownership of a
product area. A degree and some experience in a technical, analytical or customer-facing
role are preferred."""),
    ("pm_head", "product_management", "leads product strategy and product managers",
     """Head of Product

You will lead a team of four product managers and set product strategy for our accounting
software for small businesses. You will own the product vision and roadmap, decide where we
invest, coach your product managers, and work with the CEO and the head of engineering on
company priorities. Eight or more years in product, including leading product managers."""),

    # ---------------------------------------------------------------- UX design
    ("ux_designer", "ux_design", "designs how people use a product",
     """UX Designer

You will design how people book and manage appointments on our healthcare platform. You will
map user journeys, sketch and prototype in Figma, test your designs with patients and
clinicians, and work with engineers until the design ships. A portfolio showing your process
from research to final design is essential."""),
    ("ux_researcher", "ux_design", "UX research",
     """UX Researcher

You will help our teams understand the people who use our banking products. You will plan and
run interviews, usability tests and surveys, synthesise what you learn into clear insights,
and work with designers and product managers to act on them. Experience with a range of
qualitative and quantitative research methods is required."""),
    ("ux_product_designer", "ux_design", "end-to-end product design",
     """Product Designer

As our second product designer, you will own design end to end for our team-collaboration
app, from early concepts to polished interfaces. You will run design critiques, build on our
design system, prototype interactions and test them with customers. We want to see work that
shows strong interaction and visual design, and how you made decisions."""),
    ("ux_ui", "ux_design", "visual interface design and a design system",
     """UI Designer

You will shape how our travel booking site looks and feels. You will create high-fidelity
interface designs, maintain and extend our design system's components, colours and type, and
make sure every screen meets accessibility standards. You are highly skilled in Figma and have
a portfolio of digital interface work."""),
    ("ux_content", "ux_design", "designs interface words: a UX discipline",
     """Content Designer

Words are part of the design. You will write and design the interface content for our
insurance app: buttons, error messages, onboarding flows and help content. You will test
content with users, build a content style guide, and work alongside product designers from
the first sketch. A portfolio of interface content work is required."""),
    ("ux_service", "ux_design", "designs services and journeys",
     """Service Designer

You will redesign how residents apply for council permits, across the website, phone and
service counters. You will map end-to-end journeys, run workshops with staff and residents,
prototype new service models, and work with digital and operations teams to deliver them.
Experience with service design methods in the public sector is preferred."""),
    ("ux_lead", "ux_design", "leads design work and designers",
     """Lead UX Designer

You will lead UX for our e-commerce platform and mentor three designers. You will set design
direction, review your team's work, run research with customers, and make sure design has a
voice in product decisions. You have at least six years of UX design experience, including
leading projects and coaching other designers."""),

    # ---------------------------------------------------------------- project management
    ("pj_construction", "project_management", "delivers fit-out projects: judged by the work",
     """Project Manager, Commercial Fit-outs

You will deliver office fit-out projects from handover to completion. You will plan and
schedule the works, manage budgets and subcontractors, run site meetings, report progress
to clients, and make sure every project finishes safely, on time and on budget. Experience
managing commercial construction projects and a relevant qualification are required."""),
    ("pj_it", "project_management", "delivers system implementation projects",
     """IT Project Manager

You will run the rollout of a new finance system across our twelve hospitals. You will build
and maintain the project plan, manage risks, issues and dependencies, coordinate vendors and
internal teams, and report to the steering committee. PRINCE2 or PMP certification and
experience delivering IT implementation projects are required."""),
    ("pj_tpm", "project_management", "a technical project manager: coordinates delivery",
     """Technical Project Manager

You will coordinate the delivery of our mobile and web releases across five engineering
teams. You will plan releases, track dependencies between teams, run release readiness
reviews, and remove blockers so the teams ship on schedule. You will not set product
direction; you will make sure what is planned gets delivered. A technical background is
helpful."""),
    ("pj_programme", "project_management", "manages a programme of projects",
     """Programme Manager, Digital Transformation

You will lead a programme of six projects moving our customer services online. You will set
up governance, manage the programme budget and benefits, coordinate project managers, and
report to the executive sponsor. Experience leading large change programmes and managing
senior stakeholders is essential."""),
    ("pj_scrum", "project_management", "facilitates delivery for agile teams",
     """Scrum Master

You will help two agile teams deliver predictably. You will facilitate sprint planning,
stand-ups, reviews and retrospectives, track and remove impediments, coach the teams and
their stakeholders in scrum, and report on delivery progress. A scrum certification and at
least two years as a scrum master are required."""),
    ("pj_coordinator", "project_management", "a junior project coordination role",
     """Project Coordinator

Join our events agency and help deliver conferences for corporate clients. You will keep
project schedules and budgets up to date, book suppliers and venues, take minutes and chase
actions, and support the project managers on event days. This is an entry-level role suited
to someone organised, calm under pressure and keen to grow into project management."""),
    ("pj_implementation", "project_management", "manages customer implementation projects",
     """Implementation Project Manager

You will manage the onboarding of new enterprise customers onto our HR software. You will
plan each implementation, agree timelines and responsibilities with the customer, coordinate
our consultants and engineers, track risks, and make sure each customer goes live on the
agreed date. Experience managing customer-facing implementation projects is required."""),

    # ---------------------------------------------------------------- general
    ("gen_nurse", "general", "nursing: outside the four fields",
     """Registered Nurse, Surgical Ward

We are looking for a registered nurse to join our busy surgical ward. You will assess and
care for patients before and after surgery, administer medications, work with doctors and
allied health staff, and support patients and families through their stay. Current
registration with the nursing board and recent acute care experience are essential."""),
    ("gen_sales", "general", "sales: selling software is not building or managing it",
     """Account Executive, SaaS

You will sell our project management software to mid-sized businesses. You will manage the
full sales cycle from first call to signed contract, run product demonstrations, build a
pipeline of qualified opportunities, and meet a quarterly revenue target. Two years of B2B
software sales experience and a track record of exceeding quota are required."""),
    ("gen_retail", "general", "retail management: outside the four fields",
     """Store Manager

Lead our flagship store and a team of twenty-five. You will drive sales, manage rosters and
labour costs, recruit and train staff, keep stock levels and visual merchandising to standard,
and deliver great customer service every day. At least three years of retail management
experience is required."""),
    ("gen_accountant", "general", "accounting: data-heavy, but the work is finance",
     """Accountant

You will look after month-end close for our group of companies. You will prepare journals and
reconciliations, manage accounts payable and receivable, prepare management accounts and
support the annual audit and tax returns. A CPA or CA qualification, or progress towards one,
and strong Excel skills are required."""),
]
