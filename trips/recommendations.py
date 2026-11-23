"""Small, editable starter suggestions; replace with a destination API when one exists."""

CITY_IDEAS = {
    'kyoto': [
        ('Walk the Higashiyama lanes', 'Higashiyama'),
        ('Visit a neighborhood temple', 'Eastern Kyoto'),
        ('Explore Nishiki Market', 'Downtown Kyoto'),
        ('Stroll the Philosopher’s Path', 'Sakyo Ward'),
        ('Take a quiet morning in Arashiyama', 'Western Kyoto'),
    ],
    'tokyo': [
        ('Explore Asakusa and Senso-ji', 'Asakusa'),
        ('Walk the Meiji Shrine forest path', 'Shibuya'),
        ('Browse a local food market', 'Central Tokyo'),
        ('Spend an afternoon in a garden', 'Central Tokyo'),
        ('Discover a neighborhood café street', 'Tokyo'),
    ],
    'rome': [
        ('Walk the historic center early', 'Centro Storico'),
        ('Visit the Roman Forum area', 'Monti'),
        ('Explore Trastevere’s lanes', 'Trastevere'),
        ('Take a long lunch near Campo de’ Fiori', 'Campo de’ Fiori'),
        ('Visit a small local gallery', 'Rome'),
    ],
    'paris': [
        ('Walk the Seine and Île de la Cité', 'Seine riverbank'),
        ('Explore a neighborhood market', 'Paris'),
        ('Spend time in a small museum', 'Paris'),
        ('Wander the Marais lanes', 'Le Marais'),
        ('Take a garden break', 'Paris'),
    ],
    'singapore': [
        ('Explore the heritage streets', 'Kampong Gelam'),
        ('Taste your way through a hawker centre', 'Singapore'),
        ('Walk the Southern Ridges', 'Southern Singapore'),
        ('Visit the Botanic Gardens', 'Tanglin'),
        ('Take a waterfront evening walk', 'Marina Bay'),
    ],
    'london': [
        ('Walk a stretch of the Thames Path', 'South Bank'),
        ('Explore a neighborhood food market', 'London'),
        ('Visit a free public museum', 'London'),
        ('Wander a historic garden square', 'Central London'),
        ('Browse independent shops and cafés', 'London'),
    ],
}

COUNTRY_IDEAS = {
    'japan': ['Visit a local shrine or temple', 'Try a neighborhood bathhouse or onsen', 'Explore a covered shopping street'],
    'italy': ['Visit a historic piazza', 'Take a regional food market walk', 'Explore a small church or local museum'],
    'new zealand': ['Choose an easy scenic walking trail', 'Visit a local conservation area', 'Plan a relaxed lakeside or coastal stop'],
    'thailand': ['Visit a local temple respectfully', 'Explore a fresh market in the morning', 'Take a shaded riverside or park walk'],
}

DEFAULT_IDEAS = [
    'Get oriented with a walk around the center',
    'Visit a local museum or cultural site',
    'Explore a market and try a regional dish',
    'Spend time in a nearby park or nature area',
    'Leave time for a neighborhood stroll',
]


def ideas_for(destination, country):
    city = destination.strip().casefold()
    regional_ideas = COUNTRY_IDEAS.get(country.strip().casefold(), [])
    city_ideas = CITY_IDEAS.get(city)
    if city_ideas:
        return city_ideas
    return [(regional_ideas[index % len(regional_ideas)] if regional_ideas else DEFAULT_IDEAS[index % len(DEFAULT_IDEAS)], destination) for index in range(5)]
