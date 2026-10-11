# -*- coding: utf-8 -*-
"""HUMAN INFERENCES, kept apart from the decoded data on purpose.

The game stores club, nationality and edition only as numbers. No table of names for them was found
in client_Release.exe, string_list.bin or the archive (searched: club/country names in cp932,
UTF-16 and ASCII). So every name below is INFERRED: read off the real players who carry the code
(the evidence lists are regenerated from the data by extract_catalogue.py into codes_inferred.json).

Confidence:
  high   - several well-known team-mates / compatriots, no contradiction
  medium - one or two players, but the club/country is unambiguous for that player and season
  low    - a guess; NOT copied into catalogue.json / .tsv, only listed in codes_inferred.json
"""

# nationality byte (+0x124) -> (name, confidence)
NATIONALITY = {
    0: ("Argentina", "high"), 1: ("Italy", "high"), 2: ("Ukraine", "high"), 3: ("Netherlands", "high"),
    4: ("Spain", "high"), 5: ("Japan", "high"), 6: ("Brazil", "high"), 7: ("Poland", "high"),
    8: ("France", "high"), 9: ("Portugal", "high"),
    10: ("FR Yugoslavia", "medium"),          # Stankovic, Mihajlovic, Milosevic, Mijatovic in the 2001-02 sets
    11: ("Czech Republic", "high"), 12: ("Denmark", "high"), 13: ("Turkey", "high"), 14: ("Uruguay", "high"),
    15: ("Cameroon", "high"), 16: ("Georgia", "high"), 17: ("Chile", "high"), 18: ("Croatia", "high"),
    19: ("Greece", "high"), 20: ("South Korea", "high"), 21: ("Iran", "high"), 22: ("Sweden", "high"),
    23: ("Sierra Leone", "high"), 24: ("Romania", "high"), 25: ("Slovakia", "high"), 26: ("Albania", "high"),
    28: ("Austria", "high"), 29: ("Colombia", "high"), 30: ("Ghana", "high"), 31: ("South Africa", "high"),
    32: ("Germany", "high"), 33: ("Liechtenstein", "medium"), 34: ("Honduras", "high"), 35: ("Slovenia", "high"),
    36: ("Australia", "high"), 37: ("Senegal", "high"), 38: ("Nigeria", "high"), 39: ("Belarus", "high"),
    40: ("Paraguay", "high"), 41: ("Costa Rica", "medium"), 42: ("Lithuania", "high"),
    43: ("Serbia and Montenegro", "medium"),  # Stankovic/Kezman/Savicevic in the 2002-03..2005-06 sets
    44: ("Morocco", "high"), 45: ("Liberia", "medium"), 46: ("Ecuador", "high"), 47: ("Belgium", "high"),
    48: ("Russia", "high"), 50: ("Bosnia and Herzegovina", "high"), 51: ("Cote d'Ivoire", "high"),
    52: ("Egypt", "high"), 53: ("England", "high"), 54: ("Finland", "high"), 55: ("Hungary", "high"),
    56: ("Republic of Ireland", "high"), 57: ("Iceland", "medium"), 58: ("Mexico", "high"), 59: ("Norway", "high"),
    60: ("Peru", "high"), 61: ("Switzerland", "high"), 62: ("Tunisia", "high"), 63: ("United States", "high"),
    64: ("Wales", "high"), 65: ("Northern Ireland", "high"), 66: ("Mali", "high"), 67: ("Scotland", "high"),
    68: ("Canada", "medium"), 69: ("DR Congo", "medium"), 70: ("Bolivia", "medium"), 71: ("Armenia", "medium"),
    72: ("Serbia", "high"), 73: ("Montenegro", "medium"), 74: ("Togo", "medium"), 75: ("Guinea", "medium"),
    76: ("Bulgaria", "high"), 77: ("Israel", "medium"), 78: ("Algeria", "medium"),
    79: ("Suriname?", "low"),                 # only Jeremain Lens; he played for the Netherlands
    80: ("Venezuela", "medium"), 81: ("Burkina Faso", "medium"), 82: ("Macedonia", "medium"),
    83: ("Kenya", "medium"),
}

# club byte (+0x10C) -> (name, confidence)
CLUB = {
    0: ("Atalanta", "high"), 1: ("Bologna", "high"), 2: ("Brescia", "high"), 3: ("Chievo Verona", "high"),
    4: ("Fiorentina", "high"), 5: ("Inter", "high"), 6: ("Juventus", "high"), 7: ("Lazio", "high"),
    8: ("Lecce", "high"), 9: ("AC Milan", "high"), 10: ("Parma", "high"), 11: ("Perugia", "high"),
    12: ("Piacenza", "high"), 13: ("AS Roma", "high"), 14: ("Torino", "high"), 15: ("Udinese", "high"),
    16: ("Venezia", "high"), 17: ("Hellas Verona", "high"), 18: ("Como", "medium"), 19: ("Empoli", "high"),
    20: ("Modena", "high"), 21: ("Reggina", "high"), 22: ("Sampdoria", "high"),
    25: ("Genoa?", "low"),                    # only Kazuyoshi Miura cards
    26: ("Arsenal", "high"), 27: ("Chelsea", "high"), 28: ("Liverpool", "high"),
    29: ("Manchester United", "high"), 30: ("Ajax", "high"), 31: ("Feyenoord", "high"), 32: ("PSV", "high"),
    33: ("FC Barcelona", "high"), 34: ("Deportivo La Coruna", "high"), 35: ("Valencia", "high"),
    36: ("?", "low"), 37: ("?", "low"), 38: ("?", "low"),   # one Japanese player each (edition 9)
    39: ("Paris Saint-Germain", "high"), 40: ("Newcastle United", "high"), 41: ("Olympique Lyonnais", "high"),
    42: ("Olympique de Marseille", "high"), 43: ("Bayern Munchen", "high"), 44: ("Real Betis", "high"),
    45: ("Real Madrid", "high"), 46: ("Villarreal", "high"), 47: ("Boca Juniors", "high"),
    48: ("River Plate", "high"), 49: ("Flamengo", "high"), 50: ("Santos", "high"), 51: ("Sao Paulo", "high"),
    52: ("Girondins de Bordeaux", "high"), 53: ("LOSC Lille", "high"), 54: ("Hamburger SV", "high"),
    56: ("Atletico Madrid", "high"),
    57: ("Le Mans", "medium"), 58: ("Galatasaray", "medium"), 59: ("Celtic", "medium"),
    60: ("Werder Bremen?", "low"), 61: ("1. FC Koln?", "low"), 62: ("Yanmar Diesel?", "low"),
    63: ("Nagoya Grampus", "high"), 64: ("Catania", "medium"), 65: ("VVV-Venlo", "medium"),
    66: ("VfL Wolfsburg", "high"), 67: ("Red Bull Salzburg", "medium"), 68: ("Napoli?", "low"),
    69: ("VfL Bochum", "medium"), 70: ("Maritimo", "medium"), 71: ("Saint-Etienne", "medium"),
    72: ("VfB Stuttgart", "medium"), 73: ("?", "low"), 74: ("?", "low"),
    76: ("AZ Alkmaar", "high"), 77: ("FC Porto", "high"), 78: ("Sevilla", "high"), 79: ("FC Tokyo", "high"),
    80: ("Yokohama F. Marinos", "high"), 81: ("Kashima Antlers", "high"), 82: ("Gamba Osaka", "high"),
    83: ("CSKA Moscow", "high"), 84: ("Kawasaki Frontale", "medium"), 85: ("Grenoble", "medium"),
    86: ("Vissel Kobe", "medium"), 87: ("Shimizu S-Pulse", "medium"), 88: ("Jubilo Iwata", "medium"),
    89: ("Yokohama FC", "medium"), 90: ("Consadole Sapporo?", "low"), 91: ("Gainare Tottori?", "low"),
    92: ("Verdy Kawasaki?", "low"), 93: ("Cerezo Osaka?", "low"), 94: ("?", "low"), 95: ("?", "low"),
    96: ("?", "low"), 97: ("Sanfrecce Hiroshima", "medium"), 98: ("?", "low"), 99: ("Urawa Red Diamonds", "medium"),
    100: ("JEF United Chiba?", "low"), 101: ("Borussia Dortmund", "high"), 102: ("Benfica", "high"),
    105: ("Lierse", "medium"), 106: ("Schalke 04", "medium"), 107: ("Albirex Niigata?", "low"),
    108: ("FC Augsburg", "medium"), 115: ("?", "low"), 117: ("Manchester City", "medium"),
    123: ("(joke card)", "low"),
}

# edition byte (+0x0A) -> (label, season, basis).  All INFERRED except where 'code:' is cited.
EDITION = {
    1: ("2001-02, set A", "2001-02", "old 2005-06 build's id ranges put 24..130 in the 2001-02 game; images no###/be##"),
    2: ("2001-02, set B", "2001-02", "old id ranges: 201..509 in the 2001-02 game; images C_###_F"),
    3: ("2001-02, set C", "2001-02", "old id ranges: 550..595 in the 2001-02 game; images CA_##/CAE_##"),
    4: ("2002-03", "2002-03", "old id ranges: 600..939 in the 2002-03 game; images CNS_###"),
    5: ("2004-05 game, set 1", "2004-05", "old id ranges: 940..1023 first accepted by the 3.x (2004-2005) game; images CNS_###/CALE/CLE"),
    6: ("2004-05 game, legends", "2004-05", "cards 1020..1022 inside the 3.x special range; images CLE_/CALE_"),
    7: ("2004-05", "2004-05", "images CNS0405_###"),
    8: ("2005-06", "2005-06", "images CNS0506_###"),
    9: ("Japanese players special", "2004-05/2005-06", "images Calcio_###/SAKATUKU; ids inside the 3.x ranges"),
    10: ("2006-07", "2006-07", "images <club>0607_###"),
    12: ("2006-07 campaign", "2006-07", "images Campain0607_"),
    13: ("placeholder records (not real cards)", "", "cards 1-11 Unknown*, 12 Chairperson, 13-15 referees, 16-18 coaches; image ERROR_CARD; stats all 1"),
    15: ("2007-08", "2007-08", "images ###_F_####; between the 2006-07 and 2008-09 sets; models mostly _0708"),
    16: ("2007-08 campaign", "2007-08", "images Camp###_F_####"),
    17: ("2008-09", "2008-09", "images 0809_CardImage_"),
    18: ("2008-09, No.500+", "2008-09", "images 0809_CardImage_; set numbers 500..573"),
    19: ("2009-10", "2009-10", "images 0910_CardImage_; code: scouting (FUN_005282a0) picks edition 19 for game version 9"),
    20: ("2009-10, second issue", "2009-10", "images 0910_CardImage_; set numbers overlap edition 19"),
    21: ("2010-11", "2010-11", "images 1011_CardImage_; code: scouting picks edition 21 for game version 10"),
    22: ("2010-11, No.801+", "2010-11", "images 1011_CardImage_; set numbers 801..857"),
    23: ("2010-11, second set", "2010-11", "images 1011_CardImage_; code: scouting takes editions 21 and 23 for game version 0x66"),
    24: ("2010-11, No.801-806", "2010-11", "images 1011_CardImage_; set numbers 801..806"),
}


def name_for(table, code):
    """(name, confidence) for catalogue use: low-confidence guesses are withheld ('' , 'low')."""
    if code not in table:
        return "", "none"
    name, conf = table[code]
    return (name if conf in ("high", "medium") else ""), conf
