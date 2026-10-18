"""Synthetic text resources used ONLY by the data generator.

Each category has English (``en``), informal Hinglish (``hi``), a small set of
transliterated regional-language phrases (``rg``, tagged with an ISO code) and
store-staff shorthand (``staff``). Placeholders: {item}, {loc}, {amt}, {n}.
A leading ``[C]`` marks a template whose synthetic ground-truth severity is
Critical (e.g. a reported injury).

Regional phrases are a deliberately small, controlled sample (Tamil ``ta``,
Telugu ``te``, Marathi ``mr``, Bengali ``bn``, Kannada ``kn``). Their presence
does NOT mean StorePulse understands these languages in general.
"""
from __future__ import annotations

PHRASES: dict[str, dict] = {
    "refrigeration_failure": {
        "items": ["milk", "curd", "paneer", "butter", "cheese", "ice cream", "frozen peas", "yogurt",
                  "chicken", "fish"],
        "locs": ["dairy chiller", "freezer aisle", "cold section", "chiller unit 2", "meat counter fridge",
                 "frozen food section"],
        "en": [
            "The {loc} was not cold at all, the {item} felt warm.",
            "{item} in the {loc} was at room temperature. Fridge seems broken.",
            "Freezer not working, {item} melting everywhere in the {loc}.",
            "Chiller is clearly not cooling, the {item} packets were sweating and soft.",
            "Bought {item} today and it was warm when I picked it from the {loc}. Cooling issue?",
            "Your {loc} temperature display showed 14 degrees. Way too warm for {item}.",
            "The ice cream was completely melted and refrozen, the freezer must have failed.",
            "The {loc} was making a loud noise but not cooling, {item} was lukewarm.",
            "Water dripping from the {loc}, looks like the refrigerator has broken down.",
            "Second time this week the {loc} is warm. {item} can't be safe like this.",
        ],
        "hi": [
            "{loc} bilkul thanda nahi hai, {item} garam ho raha hai",
            "fridge kharab hai kya? {item} ekdum garam tha",
            "freezer band pada hai, {item} pighal gaya",
            "chiller cooling nahi kar raha, {item} ka packet garam",
        ],
        "rg": [
            ("ta", "{loc} la cooling illa, {item} sudaa irukku"),
            ("te", "fridge pani cheyyatledu, {item} vedi ga undi"),
            ("mr", "fridge band aahe, {item} garam zala"),
        ],
        "staff": [
            "{loc} temp 12C since morning, pls send technician",
            "chiller compressor tripped again, moved {item} to backup unit",
            "FYI {loc} not cooling, temp log shows 11 deg",
        ],
    },
    "allergen_labelling": {
        "items": ["cookies", "chocolate bar", "granola", "bread", "pasta sauce", "namkeen mix", "protein bar",
                  "biscuits", "ready meal", "muffins"],
        "locs": ["bakery section", "snacks aisle", "health food aisle", "ready meals shelf"],
        "en": [
            "The {item} label says nut-free but the ingredients mention peanuts. Dangerous for allergy sufferers.",
            "No allergen information on the {item} from your {loc}. My child has a gluten allergy.",
            "{item} packet is missing the 'contains milk' warning, my son is allergic to dairy.",
            "Allergen label on the {item} is wrong, it contains sesame which isn't declared.",
            "Your in-house {item} has no allergy warning at all, please label nuts and gluten.",
            "Mislabelled {item}: says egg free on the front, but egg is listed in the small print.",
            "[C]My daughter had an allergic reaction after eating {item} labelled as allergen free.",
        ],
        "hi": [
            "{item} pe likha hai nut free lekin andar peanut hai, allergy walon ke liye khatarnak",
            "{item} ke label pe allergen info hi nahi hai, bacche ko allergy hai",
            "label galat hai, {item} mein gluten hai par likha nahi",
        ],
        "rg": [("ta", "{item} label la allergy information illa, kuzhandhaikku allergy")],
        "staff": ["cust flagged {item} label - nut warning missing, pulled from shelf for check"],
    },
    "food_safety": {
        "items": ["chicken biryani", "sandwich", "paneer roll", "salad", "cake", "samosa", "fruit cup",
                  "bread", "fish fry"],
        "locs": ["hot food counter", "bakery", "deli counter", "ready-to-eat section"],
        "en": [
            "[C]Got food poisoning after eating {item} bought here yesterday.",
            "Found a piece of plastic inside the {item}. This is unsafe.",
            "[C]Whole family was vomiting after eating your {item}.",
            "There was a hair and something like metal wire in the {item}.",
            "The {item} from the {loc} was undercooked and raw inside.",
            "[C]My kid fell sick after the {item}, the doctor said it was contaminated food.",
            "Mould growing inside a sealed {item} pack sold as fresh.",
        ],
        "hi": [
            "[C]{item} khane ke baad pura parivar beemar ho gaya",
            "{item} mein plastic ka tukda mila, ye safe nahi hai",
            "[C]{item} kha ke ulti ho gayi, food poisoning lag raha hai",
        ],
        "rg": [],
        "staff": ["cust returned {item} saying foreign object found, kept sample aside for QA"],
    },
    "hygiene_cleanliness": {
        "items": ["chicken", "fish", "bread", "vegetables", "paneer"],
        "locs": ["meat counter", "fish section", "bakery", "vegetable section", "billing area", "washroom",
                 "entrance"],
        "en": [
            "The store was filthy, floors sticky and bins overflowing.",
            "Very unhygienic {loc}, raw meat juice all over the counter.",
            "Staff handling {item} without gloves and the same hands taking cash.",
            "Washrooms were disgusting and smelled terrible.",
            "Dirty trolleys and baskets, nobody seems to clean them.",
            "Bad smell coming from the {loc}, looks like it hasn't been cleaned for days.",
            "Garbage piled near the {loc}, extremely unhygienic for a food store.",
            "The {loc} floor was covered in dirt and the shelves were dusty.",
        ],
        "hi": [
            "store bahut ganda hai, {loc} mein kachra pada hai",
            "safai bilkul nahi hai, {loc} se badbu aa rahi thi",
            "staff bina gloves ke {item} pakad raha tha, very unhygienic",
        ],
        "rg": [
            ("mr", "dukan khup ghaan aahe, {loc} madhe kachra"),
            ("bn", "dokan ta khub nongra, {loc} e gondho"),
            ("te", "store chala dirty ga undi, {loc} lo smell"),
        ],
        "staff": ["{loc} not cleaned since last shift, bins overflowing, need housekeeping"],
    },
    "pest_sighting": {
        "items": ["rice bags", "biscuit packets", "bread", "flour", "dal"],
        "locs": ["grocery aisle", "bakery shelf", "storage area", "vegetable section", "dry fruits section"],
        "en": [
            "Saw a rat running across the {loc}!",
            "Cockroaches near the {loc}, disgusting.",
            "There were ants all over the {item}.",
            "Found a dead lizard near the {loc}.",
            "Mice droppings on the shelf next to the {item}.",
            "Flies everywhere at the {loc}, no pest control at all.",
        ],
        "hi": [
            "{loc} mein chuha ghoom raha tha",
            "cockroach dekha {item} ke paas, chhi",
            "{loc} pe bahut makkhiyan thi",
        ],
        "rg": [("ta", "{loc} la eli odudhu, romba mosam")],
        "staff": ["pest control due - rat seen in {loc} last night"],
    },
    "physical_safety_hazard": {
        "items": ["boxes", "oil cans", "glass jars", "cartons"],
        "locs": ["entrance", "aisle 4", "produce section", "billing area", "staircase", "parking ramp"],
        "en": [
            "Wet floor in the {loc} with no warning sign, I almost slipped.",
            "A shelf in the {loc} is loose and {item} nearly fell on my kid.",
            "Broken glass left on the floor near the {loc} for an hour.",
            "Exposed electrical wires hanging near the {loc}, very dangerous.",
            "The emergency exit was blocked with stock {item}.",
            "[C]Slipped on spilled oil in the {loc} and hurt my back.",
            "[C]Heavy {item} fell from the top rack and injured a customer.",
        ],
        "hi": [
            "[C]{loc} mein floor geela tha, koi sign nahi, main gir gaya",
            "upar se {item} gir gaye, chot lag sakti thi",
            "wire khula latak raha hai {loc} ke paas, bahut dangerous",
        ],
        "rg": [],
        "staff": ["[C]spill in {loc}, no wet-floor board available, customer slipped - first aid given"],
    },
    "staff_misconduct": {
        "items": ["cashier", "security guard", "floor staff", "manager"],
        "locs": ["billing counter", "entrance", "customer service desk", "fresh section"],
        "en": [
            "The {item} was extremely rude and shouted at my mother.",
            "A staff member at the {loc} used abusive language with me.",
            "[C]The security guard accused me of stealing in front of everyone.",
            "[C]A staff member made inappropriate comments to my daughter.",
            "[C]An employee was harassing a female customer near the {loc}.",
            "The {item} refused to help and was very arrogant and disrespectful.",
            "Billing staff misbehaved and threw the change at me.",
        ],
        "hi": [
            "{item} ne badtameezi ki, bahut rude tha",
            "staff ne {loc} pe gaali di",
            "[C]guard ne sabke saamne chor bola, bahut insult hua",
        ],
        "rg": [
            ("ta", "{loc} la staff romba rude ah pesinanga"),
            ("te", "staff chala rude ga matladaru"),
        ],
        "staff": ["complaint vs night shift associate - rude behaviour reported at {loc}"],
    },
    "product_quality": {
        "items": ["tomatoes", "bananas", "bread", "apples", "onions", "biscuits", "potatoes", "mangoes",
                  "spinach", "rice"],
        "locs": ["produce section", "bakery", "fruit section"],
        "en": [
            "The {item} I bought were stale and tasted bad.",
            "{item} were rotten inside even though they looked fine.",
            "Poor quality {item}, completely different from usual.",
            "The {item} was soggy and broke apart.",
            "Vegetables were wilted and old, especially the {item}.",
            "The {item} smelled off, quality has really gone down.",
            "Quality of {item} from the {loc} is very poor these days.",
        ],
        "hi": [
            "{item} ki quality bahut kharab thi",
            "{item} andar se sade hue the",
            "{item} basi tha, paisa waste",
        ],
        "rg": [("kn", "{item} quality tumba ketta ide")],
        "staff": ["cust returned {item}, quality poor - supplier batch issue?"],
    },
    "stock_shortage": {
        "items": ["atta", "milk", "eggs", "sugar", "cooking oil", "bread", "rice", "dal", "onions", "diapers"],
        "locs": ["grocery aisle", "staples section", "dairy section", "baby care aisle"],
        "en": [
            "{item} has been out of stock for a week now.",
            "Empty shelves in the {loc}, no {item} available.",
            "Came specifically for {item} but the shelf was empty again.",
            "Why is {item} always sold out in the evening?",
            "Half the {loc} is empty, please restock.",
            "The app shows {item} in stock but the store had none.",
        ],
        "hi": [
            "{item} ka stock khatam hai phir se",
            "{loc} khali pada hai, kuch nahi mila",
            "{item} roz out of stock rehta hai",
        ],
        "rg": [("mr", "{item} stock madhe nahi, shelf rikama aahe")],
        "staff": ["OOS {item} 3rd day, DC not sending, pls escalate"],
    },
    "product_availability": {
        "items": ["gluten-free bread", "organic honey", "oat milk", "imported cheese", "sugar-free biscuits",
                  "millet flour", "almond butter", "kombucha"],
        "locs": ["health food aisle", "dairy section", "bakery"],
        "en": [
            "You stopped stocking {item}, please bring it back.",
            "Why doesn't this store carry {item}? Other branches have it.",
            "Very limited range of {item}, hardly any choice.",
            "Please start selling {item}, many customers ask for it.",
            "The {item} range has been discontinued here, so disappointing.",
        ],
        "hi": [
            "{item} ab yahan milta hi nahi, wapas laao",
            "{item} ki variety bahut kam hai",
            "is store mein {item} rakhte hi nahi",
        ],
        "rg": [],
        "staff": ["many custs asking for {item}, pls add to range"],
    },
    "incorrect_price_label": {
        "items": ["olive oil", "detergent", "shampoo", "basmati rice", "coffee", "chocolates", "ghee"],
        "locs": ["personal care aisle", "grocery aisle", "home care section"],
        "en": [
            "Shelf price for {item} was {amt} but it rang up at a higher price.",
            "Price tag missing on most {item} in the {loc}.",
            "Wrong price label on {item}, the tag still shows the old price.",
            "The MRP on the {item} doesn't match the shelf label.",
            "Labels in the {loc} are for different products, very confusing.",
        ],
        "hi": [
            "{item} ka shelf pe price alag aur counter pe alag",
            "price tag galat laga hai {item} pe",
            "{loc} mein rate likha hi nahi hai",
        ],
        "rg": [],
        "staff": ["shelf labels {loc} not updated after price change, pls send new labels"],
    },
    "billing_error": {
        "items": ["milk", "shampoo", "chocolates", "detergent", "coffee", "biscuits"],
        "locs": ["billing counter", "counter 2", "express till"],
        "en": [
            "I was charged twice for the same {item}.",
            "The bill had items I never bought.",
            "The cashier scanned {item} three times and I noticed only at home.",
            "Overcharged by {amt} on my bill, no one could explain why.",
            "The receipt total was wrong and they refused to check it.",
            "An extra carry bag charge was added to my bill without asking.",
        ],
        "hi": [
            "bill mein {item} do baar chadha diya",
            "bill galat bana, {amt} zyada le liya",
            "jo liya hi nahi wo bhi bill mein tha",
        ],
        "rg": [],
        "staff": ["till {n} cust complaint double scan on {item}, refunded diff"],
    },
    "payment_failure": {
        "items": ["UPI", "card", "QR code", "POS terminal", "credit card", "debit card"],
        "locs": ["counter 3", "self checkout", "billing counter", "express till"],
        "en": [
            "My {item} payment failed at the {loc} but the money was debited.",
            "Card got declined at billing even though it works everywhere else.",
            "Payment machine at counter {n} not working, they said cash only.",
            "Paid {amt} by {item}, transaction failed but the amount was deducted from my account.",
            "The POS terminal kept showing 'transaction declined'.",
            "Scan and pay {item} at the till is not working, had to pay twice.",
            "Payment stuck on processing at the {loc}, money gone from my account.",
        ],
        "hi": [
            "{item} se payment kiya, paisa kat gaya par bill nahi bana",
            "card machine kaam nahi kar rahi, sirf cash le rahe",
            "payment fail ho gaya lekin {amt} account se cut gaye",
        ],
        "rg": [
            ("ta", "payment fail aachu, aana panam cut aayiduchu"),
            ("te", "{item} payment fail ayindi, dabbulu cut ayyayi"),
        ],
        "staff": ["POS {n} card txns failing since noon, bank server issue? pls chk",
                  "{item} payments declining at {loc}, custs angry, cash only for now"],
    },
    "app_failure": {
        "items": ["cart", "checkout page", "login screen", "search", "wishlist", "address page"],
        "locs": ["app"],
        "en": [
            "The app keeps crashing when I open the {item}.",
            "Can't log in to the app, the OTP never arrives.",
            "App shows an error at the {item}, tried five times.",
            "After the latest update the app is unusable, constantly freezing.",
            "Search in the app doesn't work, just shows a blank screen.",
            "Unable to save my address in the app, it just keeps loading.",
        ],
        "hi": [
            "app baar baar crash ho raha hai",
            "app mein login nahi ho raha, OTP nahi aata",
            "update ke baad app chal hi nahi raha",
        ],
        "rg": [],
        "staff": [],
    },
    "delivery_delay": {
        "items": ["groceries", "ice cream", "vegetables", "milk", "order"],
        "locs": ["home delivery"],
        "en": [
            "My order was supposed to arrive in 2 hours, it's been {n} hours.",
            "Delivery delayed again, no update from the delivery partner.",
            "Scheduled slot missed, my {item} came the next day.",
            "Order shows out for delivery since morning but nothing yet.",
            "Very late delivery, the {item} was useless by the time it came.",
        ],
        "hi": [
            "order abhi tak nahi aaya, {n} ghante ho gaye",
            "delivery har baar late hoti hai",
            "slot miss kar diya, koi call bhi nahi aaya",
        ],
        "rg": [("te", "delivery chala late ayindi, {item} inka raledu")],
        "staff": [],
    },
    "wrong_or_missing_items": {
        "items": ["eggs", "milk", "detergent", "rice", "atta", "shampoo", "bread"],
        "locs": ["online order"],
        "en": [
            "Received someone else's order, none of my items.",
            "{item} was missing from my delivery but I was charged for it.",
            "Got the wrong size of {item} in my order.",
            "Half the items in my online order were missing.",
            "Ordered {item} but got a substitute without anyone asking me.",
        ],
        "hi": [
            "order mein {item} tha hi nahi",
            "galat saman bhej diya, {item} ki jagah kuch aur",
            "aadhe items missing the delivery mein",
        ],
        "rg": [],
        "staff": [],
    },
    "queue_management": {
        "items": ["Saturday", "Sunday", "evening", "weekend"],
        "locs": ["billing counter", "checkout", "express lane"],
        "en": [
            "Only one billing counter open on a {item}, the queue was 30 minutes.",
            "Huge lines at the {loc}, half the counters were closed.",
            "Waited 40 minutes to pay, terrible queue management.",
            "Express lane was being used for full trolleys, nobody managing it.",
            "Long queue at the {loc} and staff didn't open more counters.",
        ],
        "hi": [
            "line bahut lambi thi, sirf ek counter khula tha",
            "billing pe aadha ghanta khada raha",
            "queue manage karne wala koi nahi",
        ],
        "rg": [
            ("ta", "billing la romba kootam, oru counter thaan open"),
            ("kn", "billing alli tumba queue ittu"),
        ],
        "staff": ["{item} rush, only {n} tills staffed, need extra cashier"],
    },
    "equipment_failure": {
        "items": ["self checkout", "weighing scale", "escalator", "lift", "trolleys", "lights"],
        "locs": ["produce section", "entrance", "first floor", "parking"],
        "en": [
            "Self checkout machines were all out of order.",
            "The weighing scale at the {loc} is broken.",
            "Escalator not working for weeks, hard for elderly customers.",
            "Trolley wheels are broken, impossible to push.",
            "Half the lights in the {loc} are not working.",
            "The lift is out of service again.",
        ],
        "hi": [
            "self checkout machine kharab padi hai",
            "{loc} ki weighing machine kaam nahi kar rahi",
            "escalator kai dino se band hai",
        ],
        "rg": [],
        "staff": ["{item} at {loc} down again, maintenance ticket raised"],
    },
    "staff_availability": {
        "items": ["help desk", "fresh counter", "electronics section"],
        "locs": ["home section", "electronics section", "fresh counter"],
        "en": [
            "No staff around to help find anything.",
            "Couldn't find a single employee in the {loc} to ask.",
            "The store looks understaffed, nobody at the {item}.",
            "Waited ages at the {loc}, no one came to serve.",
        ],
        "hi": [
            "help ke liye koi staff nahi tha",
            "{loc} pe poochne ke liye koi banda hi nahi tha",
        ],
        "rg": [],
        "staff": ["short staffed today, {n} absent, {loc} uncovered"],
    },
    "refund_return": {
        "items": ["mixer", "shoes", "shirt", "kettle", "headphones"],
        "locs": ["customer service desk"],
        "en": [
            "Refund for my returned {item} still not received after 2 weeks.",
            "Store refused to accept the return of an unopened {item}.",
            "They gave store credit instead of a refund for the {item}.",
            "Refund initiated but the money is still not credited.",
        ],
        "hi": [
            "refund abhi tak nahi aaya",
            "{item} wapas lene se mana kar diya",
        ],
        "rg": [],
        "staff": [],
    },
    "loyalty_rewards": {
        "items": ["points", "membership", "rewards"],
        "locs": ["account"],
        "en": [
            "Loyalty points not credited for my last purchase.",
            "My reward points disappeared from my account.",
            "Couldn't redeem my points at the till.",
            "Membership discount not applied to my bill.",
        ],
        "hi": [
            "points add nahi hue last purchase ke",
            "reward points account se gayab ho gaye",
        ],
        "rg": [],
        "staff": [],
    },
    "promotion_mismatch": {
        "items": ["juice", "detergent", "biscuits", "shampoo", "chocolates", "oil"],
        "locs": ["billing counter"],
        "en": [
            "The buy one get one offer on {item} wasn't applied at billing.",
            "Advertised discount on {item} not given at the counter.",
            "The offer poster says 20% off but the bill shows full price.",
            "My coupon was valid but the cashier said the offer had ended.",
        ],
        "hi": [
            "{item} pe offer laga tha par bill mein discount nahi mila",
            "poster pe 20% off likha tha, diya nahi",
        ],
        "rg": [],
        "staff": ["promo on {item} not loaded in POS, custs complaining"],
    },
    "packaging_damage": {
        "items": ["juice", "milk", "detergent", "biscuits", "oil", "flour"],
        "locs": ["grocery aisle"],
        "en": [
            "The {item} packets were torn and leaking.",
            "Received crushed boxes, the {item} was damaged in transit.",
            "Many dented cans of {item} on the shelf.",
            "The seal on the {item} was broken when I opened it.",
        ],
        "hi": [
            "{item} ka packet phata hua tha",
            "{item} ka dabba pichka hua aaya",
        ],
        "rg": [],
        "staff": ["inbound {item} cases crushed, {n} units damaged, DC informed"],
    },
    "expired_product": {
        "items": ["bread", "yogurt", "cheese", "juice", "biscuits", "milk", "ketchup"],
        "locs": ["dairy section", "bakery", "grocery aisle"],
        "en": [
            "Found expired {item} on the shelf, the best before date was last week.",
            "You sold me {item} that expired two days ago.",
            "Several {item} packs past their expiry date in the {loc}.",
            "The {item} I bought had an expiry date of yesterday.",
        ],
        "hi": [
            "expired {item} bech rahe ho",
            "{item} ki expiry date nikal chuki thi",
            "date nikla hua {item} shelf pe rakha hai",
        ],
        "rg": [("ta", "expiry aana {item} vikkiringa")],
        "staff": ["date check: {n} expired {item} found in {loc}, removed"],
    },
    "parking_access": {
        "items": ["car", "bike", "scooter"],
        "locs": ["parking lot", "basement parking"],
        "en": [
            "The {loc} was full and there was no attendant to guide.",
            "Parking charges are too high for customers.",
            "No space for two-wheelers, cars blocking the entrance.",
        ],
        "hi": [
            "parking ki jagah hi nahi thi",
            "parking wale ne zyada paise liye",
        ],
        "rg": [],
        "staff": [],
    },
    "store_temperature_ac": {
        "items": ["afternoon", "evening"],
        "locs": ["store", "first floor"],
        "en": [
            "AC not working inside the store, it was unbearably hot.",
            "The store was stuffy and humid, no ventilation.",
            "It was freezing inside, the AC is set far too low.",
            "Fans and AC were off in the {item}, very uncomfortable.",
        ],
        "hi": [
            "store mein AC band tha, bahut garmi thi",
            "andar ghutan ho rahi thi, AC nahi chal raha",
        ],
        "rg": [],
        "staff": ["HVAC down on {loc}, store very hot, facilities informed"],
    },
    "customer_support": {
        "items": ["ticket", "complaint", "email"],
        "locs": ["helpline"],
        "en": [
            "Called customer care three times, nobody resolved my issue.",
            "The helpline kept me on hold for 45 minutes.",
            "Chat support closed my {item} without solving it.",
            "No response to my emails for a week.",
        ],
        "hi": [
            "customer care pe koi phone nahi uthata",
            "complaint ka koi jawab nahi aaya",
        ],
        "rg": [],
        "staff": [],
    },
    "accessibility": {
        "items": ["wheelchair", "pram", "walker"],
        "locs": ["entrance", "aisles"],
        "en": [
            "No ramp at the {loc}, impossible with a {item}.",
            "Aisles blocked with boxes, can't get a {item} through.",
            "No seating for elderly customers while waiting.",
            "No accessible way up for disabled customers when the lift is off.",
        ],
        "hi": [
            "wheelchair ke liye ramp nahi hai",
            "buzurgon ke baithne ki jagah nahi hai",
        ],
        "rg": [],
        "staff": [],
    },
    "account_security": {
        "items": ["wallet", "account", "saved card"],
        "locs": ["app"],
        "en": [
            "Someone placed orders from my account without my permission.",
            "Received an OTP I didn't request, then my {item} balance was gone.",
            "My personal details are visible to other users in the app.",
            "Got a fraud call from someone claiming to be your store, they knew my order details.",
        ],
        "hi": [
            "mere account se kisi ne order kar diya",
            "{item} ka balance gayab ho gaya bina OTP ke",
        ],
        "rg": [],
        "staff": [],
    },
    "store_hours_closure": {
        "items": ["9pm", "8am", "Sunday morning"],
        "locs": ["store"],
        "en": [
            "Store was closed at {item} even though timings say it is open.",
            "Shutter was half down an hour before closing time.",
            "Opened late again, waited outside for 20 minutes.",
        ],
        "hi": [
            "timing se pehle hi store band kar diya",
            "{item} ko store khula hi nahi tha",
        ],
        "rg": [],
        "staff": [],
    },
    "no_issue": {
        "items": ["vegetables", "bakery", "staff", "store"],
        "locs": ["store"],
        "en": [
            "Great store, very clean and helpful staff.",
            "Fast checkout today, thank you!",
            "Love the fresh {item} here.",
            "No issues at all, everything was perfect.",
            "Staff were very polite and helpful.",
            "Good experience overall.",
            "Very clean store, no hygiene issues at all.",
            "The dairy fridge section was nicely organised and cold.",
            "Billing was quick and the cashier was friendly.",
        ],
        "hi": [
            "bahut accha store hai",
            "staff bahut helpful tha, thank you",
            "sab kuch badhiya tha",
        ],
        "rg": [
            ("ta", "romba nalla store"),
            ("te", "store chala bagundi"),
            ("bn", "dokan ta khub bhalo"),
        ],
        "staff": [],
    },
    # Out-of-taxonomy feedback: ground truth "other". Never used for training,
    # so it tests whether the classifier abstains instead of forcing a label.
    "other": {
        "items": ["prices", "music", "website"],
        "locs": ["store"],
        "en": [
            "Prices in general are too high compared to the market.",
            "Please open a branch in my area.",
            "The background music is too loud.",
            "Can you start a recipe section on the website?",
            "Do you sell gift cards for corporate events?",
            "Is the store hiring for the festive season?",
        ],
        "hi": [
            "mere area mein bhi branch kholo",
            "kya aap log job de rahe ho",
        ],
        "rg": [("ml", "ivide puthiya shakha thurakkumo")],
        "staff": [],
    },
}

EMOJI_BY_TONE = {
    "negative": ["😡", "😤", "😠", "👎", "😞", "🙄", "🤬"],
    "sick": ["🤢", "🤮"],
    "cold": ["🥶", "❄️"],
    "money": ["💸"],
    "pest": ["🐀", "🪳"],
    "positive": ["👍", "😊", "🙏", "❤️", "👌"],
}

CATEGORY_TONE = {
    "food_safety": "sick",
    "refrigeration_failure": "cold",
    "payment_failure": "money",
    "billing_error": "money",
    "pest_sighting": "pest",
    "no_issue": "positive",
}

REVIEW_PREFIXES = ["", "", "Visited the {store} branch today. ", "Went to the {store} store on {dow}. ",
                   "Regular customer here. ", "Honest review: "]
REVIEW_SUFFIXES = ["", "", " Very disappointed.", " Please fix this.", " Not happy.",
                   " Never coming back!", " Expected better."]
POSITIVE_SUFFIXES = ["", " Keep it up!", " Will visit again.", ""]
STAFF_PREFIXES = ["", "FYI ", "@SM ", "Update: ", "{store_id}: ", "urgent - "]
STAFF_SUFFIXES = ["", " pls chk", " pls advise", " will update", " - shift lead"]
CALL_OPENERS = ["Customer: ", "Caller: ", "Cust said: "]
CALL_ACKS = [
    " Agent: Apologised and raised ticket {ref}.",
    " Agent: Noted the complaint, escalating to store team.",
    " Agent: Logged as {ref}, customer to be called back.",
    " Agent: Advised customer we will investigate.",
]

ABBREVIATIONS = {
    "please": ["pls", "plz"],
    "you": ["u"],
    "your": ["ur"],
    "are": ["r"],
    "because": ["bcoz", "coz"],
    "morning": ["mrng"],
    "people": ["ppl"],
    "very": ["v", "vry"],
    "temperature": ["temp"],
    "minutes": ["mins"],
    "hours": ["hrs"],
    "payment": ["pymt"],
    "amount": ["amt"],
    "thanks": ["thx"],
    "customer": ["cust"],
    "with": ["wid", "w/"],
    "today": ["2day"],
    "not": ["nt"],
    "what": ["wat"],
}

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
