"""Ground-truth specification (hand-curated by Claude, an LLM — see PROVENANCE.md).

For each company: the 10-K it comes from (resolved by build_gt.py through
EDGAR), a verbatim ANCHOR string that locates the competition passage in the
filing's text, how many characters of passage to keep (SPAN), and the
competitors named in that passage. Each competitor is [canonical, *aliases];
build_gt.py refuses to build unless the canonical name or an alias literally
occurs in the extracted passage, so every label is checkable against the
filing text.

Tier = SEC public float (dei:EntityPublicFloat, XBRL frames API), a proxy for
fame:  large >= $10B,  mid $1B-$10B,  small < $1B.
"""

# (ticker, display name used as the product's company_name, homepage, anchor, span, competitors)
# CIKs for tickers missing from sec.gov/files/company_tickers.json
CIK_OVERRIDE = {"CWAN": "0001866368", "KORE": "0001855457", "ZYXI": "0000846475"}

SPEC = [
    # ---------------------------------------------------------------- large
    ("UBER", "Uber", "https://www.uber.com", "We also compete with other ridesharing companies", 1300, [
        ["Bolt"], ["Didi", "DiDi Global"], ["Lyft"], ["Ola"], ["Alphabet", "Waymo", "Google"],
        ["Amazon", "Zoox"], ["Tesla"], ["DoorDash"], ["Instacart", "Maplebear"], ["Gopuff"],
        ["Rappi"], ["Delivery Hero"], ["Just Eat Takeaway", "Just Eat"], ["C.H. Robinson"],
        ["Total Quality Logistics"], ["RXO"], ["XPO"], ["Echo Global Logistics"], ["DHL"]]),
    ("DASH", "DoorDash", "https://www.doordash.com", "Globally, we compete with other local on-demand delivery companies", 200, [
        ["Amazon"], ["Uber Eats", "Uber"], ["Prosus"], ["Delivery Hero"]]),
    ("ZM", "Zoom", "https://www.zoom.com", "We face competition from legacy web-based meeting services providers", 560, [
        ["Cisco Webex", "Cisco", "Webex"], ["GoTo", "GoTo Meeting", "LogMeIn"], ["Microsoft 365", "Microsoft", "Teams"],
        ["Google Workspace", "Google", "Google Meet"], ["Avaya"], ["RingCentral"], ["8x8"], ["Five9"],
        ["Genesys"], ["NICE inContact", "NICE", "CXone"], ["Amazon"], ["Apple"], ["Facebook", "Meta"]]),
    ("SNOW", "Snowflake", "https://www.snowflake.com", "Our competition includes the following", 300, [
        ["Amazon Web Services", "AWS", "Amazon", "Amazon Redshift"], ["Microsoft Azure", "Azure", "Microsoft"],
        ["Google Cloud Platform", "GCP", "Google Cloud", "Google", "BigQuery"]]),
    ("DDOG", "Datadog", "https://www.datadoghq.com", "with respect to on-premise infrastructure monitoring", 720, [
        ["IBM"], ["Microsoft"], ["SolarWinds"], ["Cisco Systems", "Cisco", "AppDynamics", "Splunk"],
        ["New Relic"], ["Dynatrace"], ["Elastic"], ["Amazon Web Services", "AWS", "Amazon", "CloudWatch"],
        ["Microsoft Azure", "Azure"], ["Google Cloud Platform", "GCP", "Google Cloud", "Google"]]),
    ("PINS", "Pinterest", "https://www.pinterest.com", "Competitors such as Amazon, Meta", 260, [
        ["Amazon"], ["Meta", "Facebook", "Instagram", "Threads"], ["Google", "YouTube", "Alphabet"],
        ["OpenAI", "ChatGPT"], ["Snap", "Snapchat"], ["Reddit"], ["TikTok", "ByteDance"], ["X", "Twitter"]]),
    ("SNAP", "Snap", "https://www.snap.com", "Our competitors range from smaller or newer companies", 420, [
        ["Alphabet", "Google", "YouTube"], ["Apple"], ["ByteDance", "TikTok"], ["Kakao"], ["LINE"],
        ["Meta", "Facebook", "Instagram", "WhatsApp", "Threads"], ["Naver"], ["Pinterest"], ["Reddit"],
        ["Tencent", "WeChat"], ["X", "Twitter"]]),
    ("WDAY", "Workday", "https://www.workday.com", "These vendors include, without limitation", 160, [
        ["Anaplan"], ["ADP"], ["Coupa"], ["Dayforce", "Ceridian"], ["Microsoft"], ["ServiceNow"], ["UKG"]]),
    ("MDB", "MongoDB", "https://www.mongodb.com", "We primarily compete with established legacy database software providers", 300, [
        ["IBM"], ["Microsoft", "SQL Server", "Azure"], ["Oracle"], ["Amazon Web Services", "AWS", "Amazon", "DynamoDB"],
        ["Google Cloud Platform", "GCP", "Google Cloud", "Google"]]),
    ("CVNA", "Carvana", "https://www.carvana.com", "Our current and future competitors include", 620, [
        ["CarMax"], ["Amazon"], ["Autobytel"], ["AutoTrader", "Autotrader"], ["Cars", "Cars.com"], ["Carfax"],
        ["CarGurus"], ["eBay Motors", "eBay"], ["Edmunds"], ["Google"], ["KBB", "Kelley Blue Book"], ["TrueCar"],
        ["Costco Auto Program", "Costco"], ["Ford"], ["General Motors", "GM"], ["Toyota"], ["Volkswagen"],
        ["Tesla"], ["Rivian"], ["Lucid"]]),
    ("ORCL", "Oracle", "https://www.oracle.com", "compete directly with certain offerings from some of the largest", 420, [
        ["Adobe"], ["Alphabet", "Google"], ["Amazon", "AWS", "Amazon Web Services"], ["Cisco"], ["Intel"],
        ["International Business Machines", "IBM"], ["Microsoft"], ["Salesforce"], ["SAP"],
        ["Hewlett-Packard Enterprise", "HPE", "Hewlett Packard Enterprise"], ["Workday"]]),
    ("RBLX", "Roblox", "https://www.roblox.com", "We compete for users and their engagement hours", 640, [
        ["Amazon"], ["Apple"], ["Meta Platforms", "Meta", "Facebook", "Instagram", "WhatsApp"], ["Google", "YouTube"],
        ["Microsoft", "Activision Blizzard", "Xbox", "Minecraft"], ["Tencent"], ["Comcast"], ["Disney"],
        ["Paramount Global", "Paramount"], ["Warner Bros Discovery", "Warner Bros"], ["Electronic Arts", "EA"],
        ["Take-Two", "Take-Two Interactive"], ["Epic Games", "Fortnite"], ["Krafton"], ["NetEase"],
        ["Valve", "Steam"], ["Netflix"], ["Spotify"], ["TikTok"], ["Pinterest"], ["X", "Twitter"],
        ["Reddit"], ["Discord"], ["Snap", "Snapchat"]]),
    ("FTNT", "Fortinet", "https://www.fortinet.com", "Among others, our competitors include", 560, [
        ["Check Point"], ["Cisco"], ["CrowdStrike"], ["F5", "F5 Networks"], ["Hewlett-Packard Enterprise", "HPE", "Hewlett Packard Enterprise", "Aruba"],
        ["Huawei"], ["Microsoft"], ["Netskope"], ["Palo Alto Networks"], ["SonicWall", "SonicWALL"],
        ["Sophos"], ["Zscaler"]]),
    ("ABNB", "Airbnb", "https://www.airbnb.com", "online travel agencies", 420, [
        ["Booking Holdings", "Booking.com", "Booking"], ["Expedia", "Expedia Group", "Vrbo"], ["Trip.com"],
        ["Google"], ["Marriott"], ["Hilton"], ["Accor"], ["Wyndham"]]),
    ("LYV", "Live Nation", "https://www.livenation.com", "primary ticketing companies such as", 330, [
        ["Tickets.com"], ["AXS"], ["Paciolan"], ["CTS Eventim", "Eventim"], ["Eventbrite"], ["eTix", "Etix"],
        ["SeatGeek"], ["Ticketek"], ["Fever"], ["StubHub"], ["Vivid Seats"], ["Viagogo"]]),
    ("SMCI", "Supermicro", "https://www.supermicro.com", "We believe our principal competitors include", 200, [
        ["Cisco"], ["Dell", "Dell Technologies"], ["Hewlett-Packard Enterprise", "HPE", "Hewlett Packard Enterprise"],
        ["Lenovo"], ["Foxconn", "Hon Hai"], ["Quanta Computer", "Quanta", "QCT"], ["Wiwynn"]]),
    # ------------------------------------------------------------------ mid
    ("DBX", "Dropbox", "https://www.dropbox.com", "Certain features of our platform compete in the cloud storage market", 560, [
        ["Microsoft", "OneDrive", "SharePoint"], ["Amazon"], ["Apple", "iCloud"], ["Google", "Google Drive"], ["Adobe"],
        ["Atlassian"], ["Slack", "Salesforce"], ["Box"], ["DocuSign"], ["Glean"], ["Guru"], ["Notion"]]),
    ("ROKU", "Roku", "https://www.roku.com", "Large companies such as Amazon, Apple, and Google offer TV streaming devices", 80, [
        ["Amazon", "Fire TV"], ["Apple", "Apple TV"], ["Google", "Chromecast", "Google TV"]]),
    ("W", "Wayfair", "https://www.wayfair.com", "Furniture Stores:", 900, [
        ["Ashley Furniture", "Ashley"], ["Bob's Discount Furniture"], ["Havertys"], ["Nebraska Furniture Mart"],
        ["Raymour & Flanigan"], ["Rooms To Go"], ["Home Depot"], ["IKEA"], ["Lowe's"], ["Costco"], ["Target"],
        ["Walmart"], ["JCPenney"], ["Macy's"], ["Neiman Marcus"], ["Arhaus"], ["At Home"], ["Container Store"],
        ["Crate and Barrel", "Crate & Barrel"], ["Design Within Reach"], ["Ethan Allen"], ["Floor & Decor"],
        ["LL Flooring"], ["Restoration Hardware", "RH"], ["Ferguson"], ["Room & Board"], ["Serena & Lily"],
        ["TJX Companies", "TJX", "HomeGoods"], ["Williams Sonoma", "Williams-Sonoma", "Pottery Barn", "West Elm"],
        ["Amazon"], ["Houzz"], ["eBay"], ["Etsy"], ["Bed Bath & Beyond", "Overstock"], ["Argos"],
        ["Canadian Tire"], ["John Lewis"], ["Leon's"], ["Next"]]),
    ("U", "Unity", "https://unity.com", "Cocos2d-x (Chukong Technologies), Godot, and Unreal Engine", 60, [
        ["Cocos2d-x", "Cocos", "Chukong"], ["Godot"], ["Unreal Engine", "Epic Games", "Unreal"]]),
    ("BOX", "Box", "https://www.box.com", "file sync and share market, our primary competitors include", 180, [
        ["Microsoft", "OneDrive", "SharePoint"], ["Google", "Google Drive"], ["Dropbox"]]),
    ("S", "SentinelOne", "https://www.sentinelone.com", "endpoint security providers, such as", 420, [
        ["CrowdStrike"], ["Carbon Black", "VMware Carbon Black"], ["Broadcom", "Symantec"], ["Trellix", "McAfee"],
        ["Microsoft", "Microsoft Defender"], ["Palo Alto Networks"]]),
    ("RNG", "RingCentral", "https://www.ringcentral.com", "traditional on-premise, hardware business communications providers", 420, [
        ["Alcatel-Lucent Enterprise", "Alcatel-Lucent"], ["Avaya"], ["Cisco", "Webex"], ["Mitel"], ["NEC"],
        ["Siemens Enterprise Networks", "Unify", "Siemens"], ["Microsoft", "Teams"], ["Zoom"]]),
    ("TDC", "Teradata", "https://www.teradata.com", "including AWS, Databricks, Google Cloud", 120, [
        ["AWS", "Amazon Web Services", "Amazon", "Amazon Redshift"], ["Databricks"], ["Google Cloud", "Google", "BigQuery"],
        ["Microsoft Azure", "Azure", "Microsoft"], ["Snowflake"]]),
    ("SAIL", "SailPoint", "https://www.sailpoint.com", "such as IBM, Microsoft, and Oracle that offer identity solutions", 260, [
        ["IBM"], ["Microsoft", "Entra", "Microsoft Entra"], ["Oracle"], ["Palo Alto Networks"], ["CyberArk"],
        ["Okta"], ["One Identity"]]),
    ("ARLO", "Arlo", "https://www.arlo.com", "Our principal competitors include Amazon (Blink and Ring)", 330, [
        ["Amazon", "Ring", "Blink"], ["Google", "Nest"], ["Canary"], ["D-Link"], ["Foxconn", "Belkin"],
        ["Night Owl"], ["Samsung"], ["SimpliSafe"], ["Swann"], ["TP-Link", "TP Link", "Tapo"], ["Eufy", "Anker"],
        ["Wyze"], ["Netatmo"], ["Logitech"], ["Bosch"], ["Instar"], ["Uniden"]]),
    ("UI", "Ubiquiti", "https://www.ui.com", "In the backhaul market, our competitors include", 420, [
        ["Cambium Networks", "Cambium"], ["Ceragon Networks", "Ceragon"], ["MikroTik", "Mikro"], ["Trango"],
        ["Tarana Wireless", "Tarana"], ["TP-Link"], ["Cisco", "Meraki"], ["Fortinet"],
        ["HPE Aruba Networks", "Aruba", "HPE", "Hewlett Packard Enterprise"], ["Juniper Networks", "Juniper"],
        ["Ruckus", "CommScope"]]),
    ("TREX", "Trex", "https://www.trex.com", "Our principal competitors include Azek", 200, [
        ["Azek", "TimberTech", "James Hardie"], ["Deckorators", "UFP Industries"], ["Fiberon", "Fortune Brands"]]),
    ("NSP", "Insperity", "https://www.insperity.com", "Our largest national competitors include", 230, [
        ["Automatic Data Processing", "ADP"], ["Paychex"], ["TriNet"], ["Vensure"], ["Rippling"]]),
    ("BHE", "Benchmark Electronics", "https://www.bench.com", "Our competitors include Celestica", 120, [
        ["Celestica"], ["Flex", "Flextronics"], ["Jabil"], ["Kimball Electronics"], ["Plexus"], ["Sanmina"]]),
    ("CWAN", "Clearwater Analytics", "https://clearwateranalytics.com", "large providers of investment operations, accounting and analytics systems", 520, [
        ["SS&C", "Advent", "SS&C Technologies"], ["State Street"], ["SAP"], ["BNY Mellon", "BNY", "Eagle"],
        ["Deutsche Börse", "SimCorp", "Simcorp"], ["BlackRock", "Aladdin"], ["FIS"], ["Broadridge"],
        ["Bloomberg", "Bloomberg AIM"], ["LayerOne"], ["Coremont"], ["Northern Trust"]]),
    ("WFRD", "Weatherford", "https://www.weatherford.com", "Our principal competitors include SLB", 80, [
        ["SLB", "Schlumberger"], ["Halliburton"], ["Baker Hughes"], ["Expro", "Expro Group"]]),
    # ---------------------------------------------------------------- small
    ("NTGR", "NETGEAR", "https://www.netgear.com", "within the enterprise markets, companies such as", 560, [
        ["Allied Telesis"], ["Arista"], ["Barracuda"], ["Buffalo"], ["Cisco"], ["Dell"], ["D-Link"],
        ["Extreme", "Extreme Networks"], ["Fortinet"], ["Huawei"], ["Hewlett-Packard Enterprise", "HPE", "Aruba", "Hewlett Packard Enterprise"],
        ["Juniper Networks", "Juniper", "Mist"], ["Mellanox", "Nvidia"], ["Palo Alto Networks"], ["QNAP"],
        ["Ruckus", "CommScope"], ["SonicWall"], ["Snap One", "SnapAV"]]),
    ("HLF", "Herbalife", "https://www.herbalife.com", "Our direct-selling competitors include companies such as", 160, [
        ["Medifast"], ["Nu Skin"], ["USANA"], ["Amway"]]),
    ("CNDT", "Conduent", "https://www.conduent.com", "Large multinational service providers such as Accenture", 520, [
        ["Accenture"], ["Cognizant"], ["TTEC"], ["Teleperformance"], ["Genpact"], ["Wipro"], ["EXL Services", "EXL", "ExlService"],
        ["Alight"], ["Willis Towers Watson", "WTW"], ["Gainwell"], ["Optum"], ["Maximus"]]),
    ("AVNW", "Aviat Networks", "https://aviatnetworks.com", "Our principal competitors include business units of large mobile", 420, [
        ["Ericsson"], ["Huawei"], ["ZTE"], ["Nokia"], ["GE Vernova", "GE"], ["Ceragon Networks", "Ceragon"],
        ["Cambium Networks", "Cambium"]]),
    ("BLZE", "Backblaze", "https://www.backblaze.com", "Some of our competitors include cloud-based services", 330, [
        ["Amazon", "Amazon Web Services", "AWS", "Amazon S3"], ["Alphabet", "Google Cloud Platform", "Google Cloud", "Google"],
        ["Microsoft", "Azure", "Microsoft Azure"], ["EMC", "Dell", "Dell EMC"], ["NetApp"]]),
    ("LAW", "DISCO", "https://csdisco.com", "legal services providers, including large dedicated legal services providers", 330, [
        ["Consilio"], ["Epiq", "Epiq Systems"], ["KLDiscovery"], ["Deloitte"], ["Ernst and Young", "EY", "Ernst & Young"],
        ["KPMG"], ["PricewaterhouseCoopers", "PwC"]]),
    ("DHX", "DHI Group", "https://www.dhigroupinc.com", "social and professional networking sites, such as LinkedIn", 420, [
        ["LinkedIn"], ["Facebook", "Meta"], ["X", "Twitter"], ["Google"], ["GitHub"], ["Stack Overflow"],
        ["CareerBuilder"], ["Monster"], ["Seek"]]),
    ("BRCC", "Black Rifle Coffee", "https://www.blackriflecoffee.com", "large international food and beverage companies like", 100, [
        ["Nestlé", "Nestle", "Nespresso"], ["Starbucks"], ["Monster", "Monster Beverage"], ["Pepsi", "PepsiCo"]]),
    ("WYY", "WidePoint", "https://www.widepoint.com", "Some of our principal competitors include", 400, [
        ["Calero", "Calero Software Solutions", "Calero-MDSL"], ["Tangoe"], ["Brightfin"], ["DMI"], ["A&T Systems"],
        ["Turning Point Global Services", "Turning Point"], ["Entrust"], ["IdenTrust"], ["XTec"], ["Amdocs", "Britebill"],
        ["Globys"], ["BMC Software", "BMC"], ["HPE", "Hewlett Packard Enterprise"], ["StratCore"], ["Next Level Technologies"]]),
    ("CXAI", "CXApp", "https://www.cxapp.com", "such as Envoy, Modo Labs, Condeco, Robin, and Petur", 60, [
        ["Envoy"], ["Modo Labs"], ["Condeco", "Eptura"], ["Robin"], ["Petur"]]),
    ("PHUN", "Phunware", "https://www.phunware.com", "Our competitors include Airship, Apadmi", 80, [
        ["Airship"], ["Apadmi"], ["Mutual Mobile"], ["Pointr"], ["Purple"]]),
    ("KORE", "KORE Wireless", "https://www.korewireless.com", "Our principal competitors include telecom carriers such as T-Mobile", 330, [
        ["T-Mobile"], ["AT&T"], ["Vodafone"], ["Telefónica", "Telefonica"], ["Verizon"], ["Aeris"],
        ["Wireless Logic"], ["Hologram"]]),
    ("XPON", "Expion360", "https://expion360.com", "lithium-ion battery manufacturers, such as Relion", 330, [
        ["Relion", "RELiON", "Brunswick"], ["Dragonfly Energy", "Battle Born", "Battle Born Batteries"], ["Renogy"],
        ["Dakota Lithium"]]),
    ("EFOI", "Energy Focus", "https://energyfocus.com", "Our primary competitors include Signify", 160, [
        ["Signify", "Philips Lighting", "Philips"], ["Osram Sylvania", "Osram", "Sylvania", "LEDVANCE"], ["LED Smart"],
        ["Energy Source Group"], ["Orion Energy Systems", "Orion"], ["Keystone Technologies", "Keystone"]]),
    ("TLF", "Tandy Leather", "https://www.tandyleather.com", "national craft chains like Michaels Stores", 200, [
        ["Michaels", "Michaels Stores"], ["Hobby Lobby"], ["Weaver Leather"], ["Springfield Leather"], ["Amazon"], ["eBay"]]),
    ("ZYXI", "Zynex Medical", "https://www.zynex.com", "Our principal competitors include International Rehabilitative Sciences", 120, [
        ["RS Medical", "International Rehabilitative Sciences"], ["EMSI", "Electromedical Products"], ["H-Wave"]]),
]
