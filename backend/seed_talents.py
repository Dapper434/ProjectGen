"""Seed the Talent pool (Part 2 — production staffing) without touching anything else.

Unlike seed.py, this is safe to run against the live factoryos.db: it only adds
Talent rows, and only when the table is empty — running it twice changes nothing.
seed.py imports TALENT_ROWS from here so a full reseed gets the same pool.

Usage: python3 seed_talents.py
"""
from dotenv import load_dotenv

load_dotenv()

from database import init_db, db_session
from models import Talent

TALENT_ROWS = [
    dict(name='Wanjiru Kamau', title='Producer & Project Manager',
         skills=['production management', 'call sheets', 'budgeting', 'client comms', 'scheduling'],
         day_rate_kes=60000, availability='available', location='Nairobi', years_experience=9,
         highlight='Ran 40+ corporate productions, including KCB town halls.'),
    dict(name='Brian Otieno', title='Creative Director',
         skills=['brand strategy', 'art direction', 'campaign concepts', 'storyboarding'],
         day_rate_kes=90000, availability='available', location='Nairobi', years_experience=12,
         highlight='Led creative on three Loeries-shortlisted campaigns.'),
    dict(name='Aisha Noor', title='Video Producer',
         skills=['video production', 'interview direction', 'executive testimonials', 'crew management'],
         day_rate_kes=70000, availability='available', location='Nairobi', years_experience=8,
         highlight='Directed C-suite video series for two of Kenya\'s top banks.'),
    dict(name='Dennis Mwangi', title='Videographer & Camera Operator',
         skills=['cinematography', 'Sony FX6', 'lighting', 'drone piloting'],
         day_rate_kes=45000, availability='available', location='Nairobi', years_experience=6,
         highlight='KCAA-licensed drone pilot; shoots on FX6 and FX3.'),
    dict(name='Grace Achieng', title='Video Editor & Motion Designer',
         skills=['video editing', 'Premiere Pro', 'After Effects', 'motion graphics', 'color grading'],
         day_rate_kes=50000, availability='on_project', available_from='Aug 3', location='Nairobi',
         years_experience=7, highlight='Cut launch films for Safaricom and EABL brands.'),
    dict(name='Peter Njoroge', title='Graphic Designer',
         skills=['layout design', 'digital toolkits', 'Canva templates', 'print production', 'brand guidelines'],
         day_rate_kes=40000, availability='available', location='Nairobi', years_experience=5,
         highlight='Built brand toolkits used across 200+ bank branches.'),
    dict(name='Lucy Wambui', title='Senior Strategist',
         skills=['communications strategy', 'change management', 'employee engagement', 'workshops'],
         day_rate_kes=80000, availability='available', location='Nairobi', years_experience=11,
         highlight='Ex-consultancy; led change comms for a 6-month core banking migration.'),
    dict(name='Kevin Kiptoo', title='Event Producer',
         skills=['event production', 'hybrid events', 'stage management', 'AV coordination', 'vendor management'],
         day_rate_kes=55000, availability='available', location='Nairobi', years_experience=8,
         highlight='Produced 300-pax hybrid townhalls with live simulcast.'),
    dict(name='Faith Mutua', title='Copywriter',
         skills=['copywriting', 'scripts', 'internal comms', 'speech writing'],
         day_rate_kes=35000, availability='available', location='Nairobi', years_experience=6,
         highlight='Writes exec scripts and manifesto copy in English & Swahili.'),
    dict(name='Samuel Ochieng', title='Photographer',
         skills=['corporate photography', 'event coverage', 'photo editing'],
         day_rate_kes=35000, availability='on_project', available_from='Jul 29', location='Mombasa',
         years_experience=10, highlight='House photographer for two annual banking summits.'),
    dict(name='Njeri Kariuki', title='Social Media Manager',
         skills=['social strategy', 'content calendars', 'influencer management', 'community management', 'reporting'],
         day_rate_kes=40000, availability='available', location='Nairobi', years_experience=5,
         highlight='Managed 15-creator campaign for an FMCG launch.'),
    dict(name='David Baraka', title='Sound Engineer',
         skills=['location sound', 'audio mixing', 'podcast production', 'voiceover recording'],
         day_rate_kes=38000, availability='available', location='Nairobi', years_experience=9,
         highlight='Location sound on 100+ corporate shoots; owns full Rode rig.'),
    dict(name='Mercy Chebet', title='Account Director',
         skills=['client relationship', 'project governance', 'reporting', 'budget control'],
         day_rate_kes=75000, availability='available', location='Nairobi', years_experience=10,
         highlight='Oversees the agency\'s three largest retainer accounts.'),
    dict(name='Tom Musyoka', title='Motion Designer & Animator',
         skills=['2D animation', 'explainer videos', 'After Effects', 'kinetic typography'],
         day_rate_kes=48000, availability='available', location='Nakuru', years_experience=6,
         highlight='Animated explainer series for a telco self-care app.'),
]


def seed_talents():
    init_db()
    existing = db_session.query(Talent).count()
    if existing:
        print(f"Talent pool already seeded ({existing} talents) — nothing to do.")
        return
    db_session.add_all([Talent(**row) for row in TALENT_ROWS])
    db_session.commit()
    print(f"Seeded {len(TALENT_ROWS)} talents.")


if __name__ == '__main__':
    seed_talents()
