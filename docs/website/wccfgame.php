<?php
/**
 * WCCF Online - the game link (WCCF\docs\PLAN-ACCOUNTS-AND-CARDS.md, phase 1). A player's kit signs in with the
 * player's wccf.online account the way a TV does: the kit asks for a code, the player opens wccf.online, signs in (or
 * registers) and approves the code, and the kit collects a token it keeps for joining the online server. The game
 * server checks a token with who-am-I. Poll keys and tokens are stored only as SHA-256 hashes.
 *
 * JSON, POST only, through MyBB's xmlhttp.php (hook "xmlhttp"):
 *   xmlhttp.php?action=wccf_link_start   kit=<kit version>  -> {code, poll, url, expires_in, interval}
 *   xmlhttp.php?action=wccf_link_poll    poll=<poll key>    -> {status: waiting | expired | approved (+ token, username,
 *                                                               handed over once) | collected | refused}
 *   xmlhttp.php?action=wccf_whoami       token=<token>      -> {uid, username}; 401 unknown or revoked; 403 banned
 *   xmlhttp.php?action=wccf_signout      token=<token>      -> {signed_out: true/false}; the token is refused from then on
 *   xmlhttp.php?action=wccf_club         token=<token>      -> the latest saved club card {seq, sha256, card (base64)}, or {seq: 0};
 *                                                               after a cut match our servers saw, its card made and kept
 *                                                               here first (wccfgame_cut_version)
 *   xmlhttp.php?action=wccf_club_save    token, base, card  -> {seq, sha256}; 409 when base is not the latest's sha256
 *                                                               (another PC saved since); 422 refused, and why (the game
 *                                                               would not play it, an older save, another card before
 *                                                               the contract ended, a player the account does not own,
 *                                                               the id every older kit card shares); 429 too many
 *   xmlhttp.php?action=wccf_owned        token=<token>      -> {uid, username, cards: [card numbers, one per copy owned],
 *                                                               starter_given_now}; a new player's first ask gives the
 *                                                               starter 11 (phase 2: the online club)
 *   xmlhttp.php?action=wccf_formation    token, cards       -> {kept: n}: the cards on the account's table and where
 *                                                               each stands, [[card, x, y], ...] as the kit's board has
 *                                                               them, for its profile (wccfprofile.php); 422 refused, and
 *                                                               why (a card the account does not own, out of the table)
 * The page, through misc.php (hook "misc_start"): misc.php?action=wccf_link[&code=XXXX-XXXX] - sign in or register,
 * then approve. A member who registers from it is sent back to it (hook "member_do_register_end").
 * Tables (InnoDB; made by _install, which apply.php runs): wccf_link (the codes), wccf_tokens; wccf_cards (the card
 * list - apply.php loads it from setup/cards.tsv), wccf_accounts (one row per player: the starter given, once),
 * wccf_owned (one row per copy owned: its own id, the card, starter/match, when), wccf_club_versions (every saved
 * version of each account's club card: its number, its sha256 and the one it was built on, the card (base64), its id,
 * serial and use counter - checked by wccfgame_card_read, the rules of the kit's own decoder).
 * Written 2026-10-14.
 */

if (!defined('IN_MYBB')) {
    die('Direct initialization of this file is not allowed.');
}

$plugins->add_hook('xmlhttp', 'wccfgame_xmlhttp');
$plugins->add_hook('misc_start', 'wccfgame_page');
$plugins->add_hook('member_do_register_end', 'wccfgame_after_register');

const WCCFGAME_CODE_LIFE = 600;       // seconds a code can be approved in
const WCCFGAME_COLLECT_LIFE = 600;    // seconds after approval the kit can still collect its token
const WCCFGAME_STARTS_PER_IP = 10;    // codes one address may ask for within WCCFGAME_CODE_LIFE
const WCCFGAME_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';  // no 0/O or 1/I to misread
const WCCFGAME_STARTER = ['GK' => 1, 'DF' => 4, 'MF' => 4, 'FW' => 2];   // the starter 11: REGULAR cards, a playable shape
const WCCFGAME_TABLES = ['wccf_link', 'wccf_tokens', 'wccf_cards', 'wccf_accounts', 'wccf_owned', 'wccf_club_versions',
                         'wccf_witness', 'wccf_formations'];
// phase 3, a card per finished match: the game servers that may say "this account finished a match" (wccf_witness) -
// name => the SHA-256 of its secret (the secret itself only on that server, data\server_secret.txt; never here)
const WCCFGAME_SERVERS = [
    'this-pc-test' => '3d43e6d542b326f197459dae58c1785462439c186e077c91a0269b6bd9ff7b28',   // Ali's PC: the test kit's server
    'azure-paris' => 'd4f2e860df894945b1d1d580c71dd08a8caafd5b062036ae5f057675389dccb6',    // the Azure server (Paris,
    // 20.111.35.46): its secret made there and never sent (.work\release1011\_vast\az_kit7_secret.ps1, 2026-10-14)
];
const WCCFGAME_ODDS_BETTER = 500;       // per 10000: a card better than black (RARE, LEGEND, ALL TIME LEGEND) - the
                                        // owner raised it from 2.5% to 5% ("more rares, gently", Discord feedback)
const WCCFGAME_ODDS_LUCK = 25;          // per 10000 added for each match card since the account's last one better
                                        // than black (bad-luck protection): 5% + 0.25% a miss = about 13 games a rare
const WCCFGAME_ODDS_WHITE = 700;        // per 1000 of the rest: white (REGULAR); the others black (SPECIAL) - the
                                        // owner's own numbers (the panel's dealt-card test, 2026-10-09)
const WCCFGAME_CARD_GAP = 240;          // seconds: at most one card per account in that time (a match takes longer)
// a club card file as the kit keeps it (code/hardware/card_reader.py, code/cards/decode.py and schema.py)
const WCCFGAME_CARD_BYTES = 4112;       // a 16-byte header + 256 blocks of 16
const WCCFGAME_COPY_BYTES = 0x690;      // one copy of the club's data (blocks 8-112, then 113-217): 1,676 + a checksum
const WCCFGAME_PAYLOAD_BYTES = 0x68C;
const WCCFGAME_PLAYER_BIT = 6688;       // Player[0].PLAYER_CARD_NO's first bit in a copy, 14 bits; Player[i] 312 bits on
const WCCFGAME_SAVES_PER_MINUTE = 30;   // club card saves one account may send in a minute
const WCCFGAME_TABLE_MAX = 20;          // cards on a table the kit's card reader takes (code/cards/formation.py: 1-20)
// The chain check (wccfgame_chain, 2026-10-14, after the cut-match test): fields of a club's data, [first bit, width,
// how many, bits from one to the next] - generated from the kit's decoder (code/cards/decode.py LAYOUT), never typed.
// START was seen to change only the open mark, the new players' marks and, after a cut, the bad endings; the game's
// own penalties only take away. So between a match's end and the next start nothing in WCCFGAME_GROW may grow and
// nothing in WCCFGAME_SHRINK may shrink.
const WCCFGAME_CARD_ID = [263, 32];             // SystemInfo.SYSTEM_CARD_ID: another = another card (a manager transfer)
const WCCFGAME_BAD_ENDINGS = [596, 7];          // UserInfo.USER_INJUSTICE_NUM: + 1 at the start after a cut
const WCCFGAME_OPEN_MARK = 595;                 // UserInfo.USER_INJUSTICE_FLAG: set at START and when playing on
const WCCFGAME_GROW = [
    'COACH_SALARY' => [1529, 20, 1, 20],
    'COACH_SUCCESSION_SALARY' => [1549, 20, 1, 20],
    'COACH_LEVEL' => [1585, 5, 1, 5],
    'COACH_TOTAL_WIN_NUM' => [1809, 17, 1, 17],
    'COACH_TOTAL_DRAW_NUM' => [1826, 17, 1, 17],
    'COACH_TOTAL_CHAMPIONSHIP_NUM' => [1860, 10, 30, 10],
    'COACH_TOTAL_RL_NUM' => [2160, 16, 1, 16],
    'COACH_MAX_OFFICIAL_SERIES_WIN' => [2176, 8, 1, 8],
    'CLUB_TRADE_RIGHT_NUM' => [503, 2, 1, 2],
    'CLUB_TRADE_REMAINDER_NUM' => [505, 2, 1, 2],
    'CLUB_GET_PRIZE' => [3596, 24, 1, 24],
    'CLUB_FINANCIAL_POITN' => [3620, 24, 1, 24],
    'CLUB_RECORD_WIN' => [5439, 8, 1, 8],
    'CLUB_RECORD_DRAW' => [5447, 8, 1, 8],
    'CLUB_RECORD_MAX_SERIES_WIN' => [5479, 8, 1, 8],
    'CLUB_RECORD_MAX_OFFICIAL_SERIES_WIN' => [5503, 8, 1, 8],
    'CLUB_OFFICIAL_TOTAL_POINT' => [5511, 9, 1, 9],
    'CLUB_RL_WIN' => [5587, 4, 1, 4],
    'CLUB_RL_DRAW' => [5591, 4, 1, 4],
    'CLUB_RL_GET_GOAL' => [5603, 6, 1, 6],
    'TITLE_TOTAL_WIN_NUM' => [11688, 8, 30, 40],
    'TITLE_TOTAL_CHAMPIONSHIP_NUM' => [11712, 7, 30, 40],
    'CLUB_WT_POINT' => [12900, 20, 1, 20],
    'CLUB_WT_POINT_MAX' => [12880, 20, 1, 20],
];
const WCCFGAME_SHRINK = [
    'COACH_TOTAL_LOSE_NUM' => [1843, 17, 1, 17],
    'CLUB_RECORD_LOSE' => [5455, 8, 1, 8],
    'CLUB_RL_LOSE' => [5595, 4, 1, 4],
    'CLUB_RL_LOSE_GOAL' => [5609, 6, 1, 6],
    'CLUB_OFFICIAL_TOTAL_LOST_POINT' => [5520, 9, 1, 9],
    'TITLE_TOTAL_LOSE_NUM' => [11704, 8, 30, 40],
    'USER_WAN_INJUSTICE_NUM' => [603, 5, 1, 5],
];
// within a player's 312 bits, [first bit, width] - compared only while the same card holds the place (a new card in
// it is registered anew; ponytail: its starting values are not checked - add when a registration has been seen)
const WCCFGAME_PLAYER_GROW = [
    'PLAYER_OFFICIAL_GOAL' => [14, 12],
    'PLAYER_OFFICIAL_ASSIST' => [26, 12],
    'PLAYER_PARTICIPATE_NUM' => [38, 8],
    'PLAYER_MASTERY' => [80, 7],
    'PLAYER_MASTERY_OFFENCE_NUM' => [87, 5],
    'PLAYER_MASTERY_DEFENCE_NUM' => [92, 5],
    'PLAYER_MASTERY_TECHNIQUE_NUM' => [97, 5],
    'PLAYER_MASTERY_POWER_NUM' => [102, 5],
    'PLAYER_MASTERY_SPEED_NUM' => [107, 5],
    'PLAYER_MASTERY_STAMINA_NUM' => [112, 5],
    'PLAYER_ABILITY_UP_1' => [118, 5],
    'PLAYER_ABILITY_UP_2' => [123, 5],
    'PLAYER_ABILITY_UP_3' => [128, 5],
    'PLAYER_KEYPLAYER_EXP' => [138, 8],
];

function wccfgame_info()
{
    return [
        'name' => 'WCCF Online game link',
        'description' => 'Links a player\'s WCCF 2010-11 kit to their account, so the online server knows who plays.',
        'website' => 'https://wccf.online',
        'author' => 'WCCF Online',
        'version' => '1.0',
        'compatibility' => '18*',
        'codename' => 'wccfgame',
    ];
}

function wccfgame_is_installed()
{
    global $db;
    foreach (WCCFGAME_TABLES as $table) {
        if (!$db->table_exists($table)) {
            return false;
        }
    }
    return $db->field_exists('broken', 'wccf_witness');      // added 2026-10-14: the chain check
}

function wccfgame_install()
{
    global $db;
    $charset = $db->build_create_table_collation();
    if (!$db->table_exists('wccf_link')) {
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_link (
            lid int unsigned NOT NULL auto_increment,
            code char(8) NOT NULL,
            poll_hash char(64) NOT NULL,
            ip varchar(45) NOT NULL default '',
            kit varchar(40) NOT NULL default '',
            created int unsigned NOT NULL default 0,
            expires int unsigned NOT NULL default 0,
            uid int unsigned NOT NULL default 0,
            approved int unsigned NOT NULL default 0,
            collected int unsigned NOT NULL default 0,
            PRIMARY KEY (lid),
            UNIQUE KEY code (code),
            UNIQUE KEY poll_hash (poll_hash),
            KEY ip_created (ip, created)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_tokens')) {
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_tokens (
            tid int unsigned NOT NULL auto_increment,
            uid int unsigned NOT NULL,
            token_hash char(64) NOT NULL,
            kit varchar(40) NOT NULL default '',
            created int unsigned NOT NULL default 0,
            last_used int unsigned NOT NULL default 0,
            revoked int unsigned NOT NULL default 0,
            PRIMARY KEY (tid),
            UNIQUE KEY token_hash (token_hash),
            KEY uid (uid)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_cards')) {
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_cards (
            card_no smallint unsigned NOT NULL,
            edition tinyint unsigned NOT NULL default 0,
            season varchar(20) NOT NULL default '',
            rarity tinyint unsigned NOT NULL,
            rarity_name varchar(20) NOT NULL default '',
            position char(2) NOT NULL,
            name_full varchar(80) NOT NULL default '',
            name_short varchar(40) NOT NULL default '',
            club varchar(60) NOT NULL default '',
            PRIMARY KEY (card_no),
            KEY rarity_position (rarity, position)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_accounts')) {
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_accounts (
            uid int unsigned NOT NULL,
            starter_at int unsigned NOT NULL default 0,
            PRIMARY KEY (uid)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_club_versions')) {           // every saved version of each account's club card
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_club_versions (
            vid int unsigned NOT NULL auto_increment,
            uid int unsigned NOT NULL,
            seq int unsigned NOT NULL,
            sha256 char(64) NOT NULL,
            base char(64) NOT NULL default '',
            card text NOT NULL,
            card_uid char(8) NOT NULL default '',
            serial int unsigned NOT NULL default 0,
            counter smallint unsigned NOT NULL default 0,
            created int unsigned NOT NULL default 0,
            ip varchar(45) NOT NULL default '',
            PRIMARY KEY (vid),
            UNIQUE KEY uid_seq (uid, seq)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_witness')) {     // what a game server saw (a club's data before / after a match)
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_witness (
            wid int unsigned NOT NULL auto_increment,
            uid int unsigned NOT NULL,
            server varchar(40) NOT NULL default '',
            kind varchar(8) NOT NULL default '',
            sha256 char(64) NOT NULL,
            body text NOT NULL,
            card_no smallint unsigned NOT NULL default 0,
            created int unsigned NOT NULL default 0,
            PRIMARY KEY (wid),
            UNIQUE KEY uid_sha (uid, sha256)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->field_exists('broken', 'wccf_witness')) {   // '' = in the chain; else why not (wccfgame_chain)
        $db->add_column('wccf_witness', 'broken', "varchar(255) NOT NULL default ''");
    }
    if (!$db->table_exists('wccf_owned')) {
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_owned (
            oid int unsigned NOT NULL auto_increment,
            uid int unsigned NOT NULL,
            card_no smallint unsigned NOT NULL,
            source varchar(10) NOT NULL default '',
            created int unsigned NOT NULL default 0,
            PRIMARY KEY (oid),
            KEY uid (uid)
        ) ENGINE=InnoDB{$charset};");
    }
    if (!$db->table_exists('wccf_formations')) {   // added 2026-10-16: the cards on each account's table, for its profile
        $db->write_query('CREATE TABLE ' . TABLE_PREFIX . "wccf_formations (
            uid int unsigned NOT NULL,
            cards text NOT NULL,
            updated int unsigned NOT NULL default 0,
            PRIMARY KEY (uid)
        ) ENGINE=InnoDB{$charset};");
    }
}

/**
 * The starter 11 for a player who has none yet: REGULAR cards in a playable shape (WCCFGAME_STARTER), never two cards
 * of one footballer (the same full name), picked with a cryptographic shuffle. Given once: the wccf_accounts row is
 * claimed first (INSERT IGNORE inside a transaction), so two asks at the same moment give one starter 11.
 * Returns 'granted', 'had' (given before), or 'no cards' (the card list is not loaded).
 */
function wccfgame_starter(int $uid): string
{
    global $db;
    $pool = [];
    $q = $db->simple_select('wccf_cards', 'card_no, position, name_full', 'rarity=1');
    while ($r = $db->fetch_array($q)) {
        $pool[] = $r;
    }
    for ($i = count($pool) - 1; $i > 0; $i--) {
        $j = random_int(0, $i);
        [$pool[$i], $pool[$j]] = [$pool[$j], $pool[$i]];
    }
    $need = WCCFGAME_STARTER;
    $names = [];
    $pick = [];
    foreach ($pool as $r) {
        $name = strtolower(trim($r['name_full']));
        if (empty($need[$r['position']]) || isset($names[$name])) {
            continue;
        }
        $need[$r['position']]--;
        $names[$name] = true;
        $pick[] = (int) $r['card_no'];
    }
    if (count($pick) !== array_sum(WCCFGAME_STARTER)) {
        return 'no cards';
    }
    $db->write_query('START TRANSACTION');
    $db->write_query('INSERT IGNORE INTO ' . TABLE_PREFIX . "wccf_accounts (uid, starter_at) VALUES ({$uid}, " . TIME_NOW . ')');
    if ($db->affected_rows() !== 1) {
        $db->write_query('ROLLBACK');
        return 'had';
    }
    foreach ($pick as $card) {
        $db->insert_query('wccf_owned', ['uid' => $uid, 'card_no' => $card, 'source' => 'starter', 'created' => TIME_NOW]);
    }
    $db->write_query('COMMIT');
    return 'granted';
}

/** match cards the account got since its last one better than black - the bad-luck count (starter cards not counted;
 * an account's earlier matches count too, so the unlucky ones are helped at once) */
function wccfgame_misses(int $uid): int
{
    global $db;
    $p = TABLE_PREFIX;
    $last = (int) $db->fetch_field($db->query("SELECT MAX(o.oid) AS m FROM {$p}wccf_owned o JOIN {$p}wccf_cards c ON "
        . "c.card_no=o.card_no WHERE o.uid={$uid} AND o.source='match' AND c.rarity>=3"), 'm');
    return (int) $db->fetch_field($db->simple_select('wccf_owned', 'COUNT(*) AS n',
        "uid={$uid} AND source='match' AND oid>{$last}"), 'n');
}

/** one card drawn for the account by the owner's odds (WCCFGAME_ODDS_*; better than black grows by WCCFGAME_ODDS_LUCK
 * with each miss), uniform within its group, never a card the account owns while its group has another -> its number,
 * or 0 (no cards) */
function wccfgame_draw(int $uid): int
{
    global $db;
    if (random_int(0, 9999) < WCCFGAME_ODDS_BETTER + WCCFGAME_ODDS_LUCK * wccfgame_misses($uid)) {
        $where = 'rarity>=3';
    } else {
        $where = random_int(0, 999) < WCCFGAME_ODDS_WHITE ? 'rarity=1' : 'rarity=2';
    }
    $new = $where . ' AND card_no NOT IN (SELECT card_no FROM ' . TABLE_PREFIX . "wccf_owned WHERE uid={$uid})";
    foreach ([$new, $where] as $w) {          // every card of the group owned already: a copy, as before
        $n = (int) $db->fetch_field($db->simple_select('wccf_cards', 'COUNT(*) AS n', $w), 'n');
        if ($n > 0) {
            return (int) $db->fetch_field($db->simple_select('wccf_cards', 'card_no', $w,
                ['order_by' => 'card_no', 'limit' => 1, 'limit_start' => random_int(0, $n - 1)]), 'card_no');
        }
    }
    return 0;
}

/** the card a finished match earns the account: drawn and owned ('match') -> its number; 0 when the account had one
 * less than WCCFGAME_CARD_GAP seconds ago (a match takes longer: nobody earns two by sending the end twice) */
function wccfgame_award(int $uid): int
{
    global $db;
    $last = (int) $db->fetch_field($db->simple_select('wccf_owned', 'MAX(created) AS t', "uid='{$uid}' AND source='match'"), 't');
    if ($last > TIME_NOW - WCCFGAME_CARD_GAP) {
        return 0;
    }
    $card = wccfgame_draw($uid);
    if ($card) {
        $db->insert_query('wccf_owned', ['uid' => $uid, 'card_no' => $card, 'source' => 'match', 'created' => TIME_NOW]);
    }
    return $card;
}

/** the MSB-first bit field at $start, $width bits wide (decode.py bits_at) */
function wccfgame_bits(string $buf, int $start, int $width): int
{
    $v = 0;
    for ($k = 0; $k < $width; $k++) {
        $i = $start + $k;
        $v = ($v << 1) | ((ord($buf[$i >> 3]) >> (7 - ($i & 7))) & 1);
    }
    return $v;
}

/** decode.py copy_check: [good, all zero] - the stored checksum is the sum of the 419 little-endian dwords, or + 1 */
function wccfgame_copy_check(string $copy): array
{
    $sum = 0;
    foreach (unpack('V*', substr($copy, 0, WCCFGAME_PAYLOAD_BYTES)) as $d) {
        $sum = ($sum + $d) & 0xFFFFFFFF;
    }
    $stored = unpack('V', substr($copy, WCCFGAME_PAYLOAD_BYTES, 4))[1];
    $zero = $sum === 0 && $stored === 0;
    return [!$zero && ($stored === $sum || $stored === (($sum + 1) & 0xFFFFFFFF)), $zero];
}

/**
 * A club card file as the game reads it, by the rules of the kit's own decoder (code/cards/decode.py read_card,
 * card_checks, game_choice; the field positions from its schema): ['uid' => hex, 'serial' => n, 'counter' => n,
 * 'players' => the 16 registered card numbers, 0 = none] - or a string: why the game would refuse it. A new (blank)
 * card has no club yet and a used-up one is never played again: both refused here too.
 */
function wccfgame_card_read(string $raw)
{
    if (strlen($raw) !== WCCFGAME_CARD_BYTES) {
        return 'it is ' . strlen($raw) . ' bytes, a club card file is ' . WCCFGAME_CARD_BYTES;
    }
    $block = function (int $n) use ($raw): string {
        return substr($raw, 16 + 16 * $n, 16);
    };
    $counter = ord($raw[5]) | (ord($raw[6]) << 8);
    if ($counter === 0xFFFF) {
        return 'a new card - no club made on it yet';
    }
    if (($counter & 0xFF) === 0) {
        return 'a used-up card (its manager moved to a new card)';
    }
    if (ord($raw[4]) === 0x20) {
        return 'its status byte is 0x20';
    }
    if ((unpack('V', substr($block(4), 8, 4))[1] & 0xF0FFFFFF) !== 0x40667195) {
        return 'its block 4 signature is wrong';
    }
    $serial = unpack('N', substr($block(6), 12, 4))[1];
    if ($serial < 10000000) {
        return 'its serial is below 10,000,000';
    }
    if ($block(7) !== $block(0)) {
        return 'block 7 is not block 0 (a copied card)';
    }
    $version = unpack('N', substr($block(8), 0, 4))[1];
    if ($version >= 1 && $version <= 4) {
        return "SYSTEM_VERSION $version is refused by the game";
    }
    $data = substr($raw, 16 + 16 * 8, 16 * 210);
    $copies = ['A' => substr($data, 0, WCCFGAME_COPY_BYTES), 'B' => substr($data, WCCFGAME_COPY_BYTES, WCCFGAME_COPY_BYTES)];
    [$aGood, $aZero] = wccfgame_copy_check($copies['A']);
    [$bGood, $bZero] = wccfgame_copy_check($copies['B']);
    if ($aZero || $bZero) {
        return 'a copy of its data is all zeros';
    }
    if (!$aGood && !$bGood) {
        return 'both copies of its data fail their checksum';
    }
    $copy = $copies[$aGood ? 'A' : 'B'];
    $players = [];
    for ($i = 0; $i < 16; $i++) {
        $players[] = wccfgame_bits($copy, WCCFGAME_PLAYER_BIT + 312 * $i, 14);
    }
    return ['uid' => bin2hex(substr($raw, 0, 4)), 'serial' => $serial, 'counter' => $counter, 'players' => $players,
            'data' => substr($copy, 0, WCCFGAME_PAYLOAD_BYTES)];
}

/** the club data in a message a game server kept: TEAM DATA RSLT (the end of a match) +0 its size (u32), +4 the data;
 * ENTRY SVR (a session's start) and TEAM DATA (each match's start) +0x38 its size (u16), +0x3a the data - '' when the
 * body is too short */
function wccfgame_msg_data(string $kind, string $b): string
{
    if ($kind === 'rslt') {
        return strlen($b) >= 4 ? substr($b, 4, unpack('V', substr($b, 0, 4))[1]) : '';
    }
    return strlen($b) >= 0x3a ? substr($b, 0x3a, unpack('v', substr($b, 0x38, 2))[1]) : '';
}

/** a club's data with the game's open mark set - what the card holds once the game leaves the locker room to play on
 * (proven 2026-10-14: version 4 + the mark == the card in the played-on match) */
function wccfgame_open_mark(string $data): string
{
    if (strlen($data) === WCCFGAME_PAYLOAD_BYTES) {
        $at = WCCFGAME_OPEN_MARK >> 3;
        $data[$at] = chr(ord($data[$at]) | (0x80 >> (WCCFGAME_OPEN_MARK & 7)));
    }
    return $data;
}

/** the account's messages in the chain (broken=''), the newest first: [['kind' => entry|team|rslt, 'data' => ...]] */
function wccfgame_rows(int $uid, int $limit = 10): array
{
    global $db;
    $rows = [];
    $q = $db->simple_select('wccf_witness', 'kind, body', "uid='{$uid}' AND broken=''", ['order_by' => 'wid',
        'order_dir' => 'DESC', 'limit' => $limit]);
    while ($r = $db->fetch_array($q)) {
        $rows[] = ['kind' => $r['kind'], 'data' => wccfgame_msg_data($r['kind'], base64_decode($r['body']))];
    }
    return $rows;
}

/**
 * What the club card holds after the message at $i of $rows (the newest first), as the game writes it [V 2026-10-14]:
 * a session's start (ENTRY SVR) - its data (START wrote the card); a match's end - its data (the locker room did); a
 * match's start inside a session (TEAM DATA) writes nothing - the card is as before it, with the open mark when that was
 * a match's end (the game marked it when playing on). TEAM DATA itself is never what the card holds: the Team entry's
 * changes are written at the locker room. null when the list runs out.
 */
function wccfgame_card_state(array $rows, int $i): ?string
{
    $played_on = false;
    for (; $i < count($rows); $i++) {
        if ($rows[$i]['kind'] === 'team') {
            $played_on = true;
            continue;
        }
        if ($rows[$i]['kind'] === 'entry') {
            return $rows[$i]['data'];
        }
        return $played_on ? wccfgame_open_mark($rows[$i]['data']) : $rows[$i]['data'];
    }
    return null;
}

/**
 * The club data our game servers last saw for the account (in the chain): what a save must equal (Ali: "it should
 * match and if it doesnt its refused"). The end of its last match - proven equal to the card's own data after that
 * locker-room save, 2026-10-14 - with the open mark too (played on from that locker room, then cut), and each session's
 * start after it (a match cut short: START wrote the card). TEAM DATA is never what a card holds. [] when no server has
 * seen the account play.
 */
function wccfgame_seen(int $uid): array
{
    $out = [];
    foreach (wccfgame_rows($uid) as $r) {             // the newest first
        if ($r['kind'] === 'entry') {
            $out[] = $r['data'];
        } elseif ($r['kind'] === 'rslt') {
            array_push($out, $r['data'], wccfgame_open_mark($r['data']));
            break;                                    // the last finished match: nothing before it counts
        }
    }
    return $out;
}

/** [name or name[k] => value] of the fields listed ([first bit, width, how many, stride]) in a club's data */
function wccfgame_values(string $data, array $fields): array
{
    $out = [];
    foreach ($fields as $name => [$bit, $width, $count, $stride]) {
        for ($k = 0; $k < $count; $k++) {
            $out[$count > 1 ? "{$name}[{$k}]" : $name] = wccfgame_bits($data, $bit + $stride * $k, $width);
        }
    }
    return $out;
}

/**
 * The chain check (2026-10-14): may $next, the club data a match starts with (ENTRY SVR), follow $prev, what our
 * servers saw last for the account - the end of its last match, or the start of one that was cut ($cut)? A cut must
 * show at the next start (bad endings + 1, as the game counts it); nothing the club is worth may grow and no loss may
 * shrink in between (WCCFGAME_GROW / _SHRINK). '' when it may follow, else why (the first fields out of line). Another
 * card id is another card - a manager transfer, or a new club: not checked here.
 */
function wccfgame_chain(string $prev, string $next, bool $cut): string
{
    $len = WCCFGAME_PAYLOAD_BYTES;
    if (strlen($prev) !== $len || strlen($next) !== $len) {
        return strlen($next) === $len ? '' : 'not a club\'s data';
    }
    [$b, $w] = WCCFGAME_CARD_ID;
    if (wccfgame_bits($prev, $b, $w) !== wccfgame_bits($next, $b, $w)) {
        return '';
    }
    $why = [];
    [$b, $w] = WCCFGAME_BAD_ENDINGS;
    [$was, $now] = [wccfgame_bits($prev, $b, $w), wccfgame_bits($next, $b, $w)];
    if ($now < $was + ($cut ? 1 : 0)) {
        $why[] = "bad endings $was -> $now" . ($cut ? ' after a cut match' : '');
    }
    foreach ([[WCCFGAME_GROW, 1], [WCCFGAME_SHRINK, -1]] as [$fields, $up]) {
        $before = wccfgame_values($prev, $fields);
        foreach (wccfgame_values($next, $fields) as $k => $v) {
            if (($v - $before[$k]) * $up > 0) {
                $why[] = "$k {$before[$k]} -> $v";
            }
        }
    }
    for ($i = 0; $i < 16; $i++) {
        $at = WCCFGAME_PLAYER_BIT + 312 * $i;
        if (wccfgame_bits($prev, $at, 14) !== wccfgame_bits($next, $at, 14)) {
            continue;                                 // another card in this place: registered anew
        }
        foreach (WCCFGAME_PLAYER_GROW as $name => [$bit, $width]) {
            [$a, $z] = [wccfgame_bits($prev, $at + $bit, $width), wccfgame_bits($next, $at + $bit, $width)];
            if ($z > $a) {
                $why[] = "Player[$i].$name $a -> $z";
            }
        }
    }
    return substr(implode(', ', array_slice($why, 0, 4)) . (count($why) > 4 ? ' ...' : ''), 0, 255);
}

/** the chain verdict for a message a game server sends (wccf_witness 'broken'), before it is kept: a start - a
 * session's (ENTRY SVR) or a match's (TEAM DATA) - checked against what the card held after our servers' last message
 * for the account (wccfgame_chain; a session's start after a start with no end = after a cut: + 1 bad ending); an end
 * takes its start's ('' when its start was not seen: our server's gap, not the player's) */
function wccfgame_verdict(int $uid, string $kind, string $body): string
{
    global $db;
    if ($kind === 'rslt') {
        $last = $db->fetch_array($db->simple_select('wccf_witness', 'kind, broken', "uid='{$uid}'",
            ['order_by' => 'wid', 'order_dir' => 'DESC', 'limit' => 1]));
        return $last && $last['kind'] !== 'rslt' && $last['broken'] !== ''
            ? substr('its start: ' . $last['broken'], 0, 255) : '';
    }
    $rows = wccfgame_rows($uid);
    $prev = $rows ? wccfgame_card_state($rows, 0) : null;
    return $prev === null ? '' : wccfgame_chain($prev, wccfgame_msg_data($kind, $body),
        $kind === 'entry' && $rows[0]['kind'] !== 'rslt');
}

/**
 * A match our servers saw start and never end (a cut) leaves the card as it was at that start: START marked it (a
 * session's start: its ENTRY SVR data), or the game marked the last end when playing on (a TEAM DATA after a match's
 * end: that end + the open mark) - and the next start counts a bad ending. When the latest kept version is the club
 * that session or match began from, the cut card is that version's file with the cut data in both copies and the game's
 * checksum (the dword sum + 1) - built so, version 1 + the cut match's ENTRY SVR gave the real cut card byte for byte,
 * and version 4 + the open mark the card in a played-on match (2026-10-14). Kept as the next version, so the next start
 * on any PC plays the cut card, and an older copy put back does not erase the cut -> that version's row; null when
 * there is no cut to keep (or another save took its place first).
 */
function wccfgame_cut_version(int $uid, ?array $latest): ?array
{
    global $db;
    $rows = $latest ? wccfgame_rows($uid) : [];
    if (!$rows || $rows[0]['kind'] === 'rslt') {
        return null;                                  // the newest is an end (or nothing): no cut
    }
    $first = 0;                                       // the session's start, or the end the match was played on from
    while ($first < count($rows) && $rows[$first]['kind'] === 'team') {
        $first++;
    }
    if ($first === count($rows)) {
        return null;
    }
    $cut = wccfgame_card_state($rows, 0);
    $from = $rows[$first]['kind'] === 'entry' ? wccfgame_card_state($rows, $first + 1) : $rows[$first]['data'];
    $raw = base64_decode($latest['card']);
    $card = wccfgame_card_read($raw);
    if ($cut === null || strlen($cut) !== WCCFGAME_PAYLOAD_BYTES || is_string($card) || $card['data'] !== $from
            || $card['data'] === $cut) {
        return null;                                  // the latest is not the club that cut session or match began from
    }
    [$b, $w] = WCCFGAME_CARD_ID;
    if (wccfgame_bits($cut, $b, $w) !== wccfgame_bits($from, $b, $w)) {
        // a manager transfer's new club, cut: it lives on a new card the website has no file of (the old card's file
        // with it would read "contract ended" for ever); the PC's new card goes up at its next start
        return null;
    }
    $sum = 0;
    foreach (unpack('V*', $cut) as $d) {
        $sum = ($sum + $d) & 0xFFFFFFFF;
    }
    $copy = $cut . pack('V', ($sum + 1) & 0xFFFFFFFF);
    $at = 16 + 16 * 8;                                // copy A, then copy B right after it
    $cut = substr($raw, 0, $at) . $copy . $copy . substr($raw, $at + 2 * WCCFGAME_COPY_BYTES);
    $db->write_query('INSERT IGNORE INTO ' . TABLE_PREFIX . 'wccf_club_versions (uid, seq, sha256, base, card, card_uid, '
        . 'serial, counter, created, ip) VALUES (' . $uid . ', ' . ((int) $latest['seq'] + 1) . ", '" . hash('sha256', $cut)
        . "', '" . $db->escape_string($latest['sha256']) . "', '" . base64_encode($cut) . "', '"
        . $db->escape_string($latest['card_uid']) . "', " . (int) $latest['serial'] . ', ' . (int) $latest['counter']
        . ', ' . TIME_NOW . ", 'cut match')");
    return $db->affected_rows() === 1 ? wccfgame_club_latest($uid) : null;
}

/** the account's latest saved club card version (a wccf_club_versions row), or null */
function wccfgame_club_latest(int $uid): ?array
{
    global $db;
    $row = $db->fetch_array($db->simple_select('wccf_club_versions', '*', "uid='{$uid}'",
        ['order_by' => 'seq', 'order_dir' => 'DESC', 'limit' => 1]));
    return $row ?: null;
}

/** the member a POSTed token belongs to - or the JSON 401 / 403 answer, and the end of the request */
function wccfgame_token_user(): array
{
    global $mybb, $db;
    $hash = hash('sha256', $mybb->get_input('token'));
    $row = $db->fetch_array($db->simple_select('wccf_tokens', '*', "token_hash='{$hash}' AND revoked=0", ['limit' => 1]));
    $user = $row ? get_user((int) $row['uid']) : null;
    if (!$user) {
        wccfgame_json(401, ['error' => 'unknown or revoked sign-in - sign in again from the game']);
    }
    if (wccfgame_banned($user)) {
        wccfgame_json(403, ['error' => 'this account is banned']);
    }
    if ($row['last_used'] < TIME_NOW - 60) {
        $db->update_query('wccf_tokens', ['last_used' => TIME_NOW], "tid='" . (int) $row['tid'] . "'");
    }
    return $user;
}

function wccfgame_banned(array $user): bool
{
    global $cache;
    $groups = $cache->read('usergroups');
    return !empty($groups[$user['usergroup']]['isbannedgroup']);
}

function wccfgame_shown(string $code): string
{
    return substr($code, 0, 4) . '-' . substr($code, 4);
}

function wccfgame_json(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body);
    exit;
}

// ---- the kit's and the server's JSON ----------------------------------------------------------------------------

function wccfgame_xmlhttp()
{
    global $mybb, $db;
    $action = $mybb->get_input('action');
    if (strpos($action, 'wccf_') !== 0) {
        return;
    }
    if ($mybb->request_method !== 'post') {
        wccfgame_json(405, ['error' => 'POST only']);
    }
    $now = TIME_NOW;

    if ($action === 'wccf_link_start') {
        $ip = $db->escape_string(get_ip());
        $recent = (int) $db->fetch_field($db->simple_select('wccf_link', 'COUNT(*) AS n',
            "ip='{$ip}' AND created>" . ($now - WCCFGAME_CODE_LIFE)), 'n');
        if ($recent >= WCCFGAME_STARTS_PER_IP) {
            wccfgame_json(429, ['error' => 'too many sign-in codes from this address - wait a few minutes']);
        }
        $db->delete_query('wccf_link', 'expires<' . ($now - 86400));
        $kit = my_substr(preg_replace('/[^A-Za-z0-9 ._:+-]/', '', $mybb->get_input('kit')), 0, 40);
        $code = '';
        for ($try = 0; $try < 5 && $code === ''; $try++) {
            $c = '';
            for ($i = 0; $i < 8; $i++) {
                $c .= WCCFGAME_ALPHABET[random_int(0, strlen(WCCFGAME_ALPHABET) - 1)];
            }
            if (!$db->fetch_field($db->simple_select('wccf_link', 'lid', "code='{$c}'"), 'lid')) {
                $code = $c;
            }
        }
        if ($code === '') {
            wccfgame_json(503, ['error' => 'no free code - try again']);
        }
        $poll = bin2hex(random_bytes(32));
        $db->insert_query('wccf_link', [
            'code' => $code,
            'poll_hash' => hash('sha256', $poll),
            'ip' => $ip,
            'kit' => $db->escape_string($kit),
            'created' => $now,
            'expires' => $now + WCCFGAME_CODE_LIFE,
        ]);
        wccfgame_json(200, [
            'code' => wccfgame_shown($code),
            'poll' => $poll,
            'url' => $mybb->settings['bburl'] . '/misc.php?action=wccf_link&code=' . wccfgame_shown($code),
            'expires_in' => WCCFGAME_CODE_LIFE,
            'interval' => 3,
        ]);
    }

    if ($action === 'wccf_link_poll') {
        $hash = hash('sha256', $mybb->get_input('poll'));
        $row = $db->fetch_array($db->simple_select('wccf_link', '*', "poll_hash='{$hash}'", ['limit' => 1]));
        if (!$row) {
            wccfgame_json(404, ['status' => 'unknown']);
        }
        if ($row['collected']) {
            wccfgame_json(410, ['status' => 'collected']);
        }
        if (!$row['uid']) {
            wccfgame_json(200, ['status' => $row['expires'] < $now ? 'expired' : 'waiting']);
        }
        if ($row['approved'] + WCCFGAME_COLLECT_LIFE < $now) {
            wccfgame_json(200, ['status' => 'expired']);
        }
        $user = get_user((int) $row['uid']);
        if (!$user || wccfgame_banned($user)) {
            wccfgame_json(403, ['status' => 'refused']);
        }
        // the token goes to one caller only: the update below succeeds once
        $db->update_query('wccf_link', ['collected' => $now], "lid='" . (int) $row['lid'] . "' AND collected=0");
        if ($db->affected_rows() !== 1) {
            wccfgame_json(410, ['status' => 'collected']);
        }
        $token = bin2hex(random_bytes(32));
        $db->insert_query('wccf_tokens', [
            'uid' => (int) $user['uid'],
            'token_hash' => hash('sha256', $token),
            'kit' => $db->escape_string($row['kit']),
            'created' => $now,
            'last_used' => $now,
        ]);
        wccfgame_json(200, ['status' => 'approved', 'token' => $token, 'username' => $user['username']]);
    }

    if ($action === 'wccf_signout') {               // the kit's SIGN OUT (SETTINGS): this token is refused from now on
        $hash = hash('sha256', $mybb->get_input('token'));
        $db->update_query('wccf_tokens', ['revoked' => 1], "token_hash='{$hash}' AND revoked=0");
        wccfgame_json(200, ['signed_out' => $db->affected_rows() === 1]);
    }

    if ($action === 'wccf_whoami') {
        $user = wccfgame_token_user();
        wccfgame_json(200, ['uid' => (int) $user['uid'], 'username' => $user['username']]);
    }

    if ($action === 'wccf_owned') {
        $user = wccfgame_token_user();
        $uid = (int) $user['uid'];
        $state = 'had';
        if (!$db->fetch_field($db->simple_select('wccf_accounts', 'uid', "uid='{$uid}'"), 'uid')) {
            $state = wccfgame_starter($uid);
            if ($state === 'no cards') {
                wccfgame_json(503, ['error' => 'the card list is not loaded on the website yet']);
            }
        }
        $cards = [];
        $q = $db->simple_select('wccf_owned', 'card_no', "uid='{$uid}'", ['order_by' => 'oid']);
        while ($r = $db->fetch_array($q)) {
            $cards[] = (int) $r['card_no'];
        }
        wccfgame_json(200, ['uid' => $uid, 'username' => $user['username'], 'cards' => $cards,
            'starter_given_now' => $state === 'granted']);
    }

    if ($action === 'wccf_witness') {               // a game server saw an account's club: a session's start ("entry",
        $server = $mybb->get_input('server');       // ENTRY SVR), a match's start ("team", TEAM DATA - played-on
        $known = WCCFGAME_SERVERS[$server] ?? '';   // matches too) or a match's end ("rslt", TEAM DATA RSLT: one card).
        // Only our servers: their secret, never a token
        if ($known === '' || !hash_equals($known, hash('sha256', $mybb->get_input('secret')))) {
            wccfgame_json(403, ['error' => 'not one of our game servers']);
        }
        $uid = $mybb->get_input('uid', MyBB::INPUT_INT);
        $user = $uid > 0 ? get_user($uid) : null;
        if (!$user || wccfgame_banned($user)) {
            wccfgame_json(404, ['error' => 'no such account']);
        }
        $kind = $mybb->get_input('kind');
        $body = base64_decode($mybb->get_input('body'), true);
        if (!in_array($kind, ['entry', 'team', 'rslt'], true) || $body === false || $body === '' || strlen($body) > 0x2000) {
            wccfgame_json(422, ['error' => 'not a message the game sends']);
        }
        $sha = hash('sha256', $body);
        $srv = $db->escape_string($server);
        $broken = wccfgame_verdict($uid, $kind, $body);               // before it is kept: what came before it
        $db->write_query('INSERT IGNORE INTO ' . TABLE_PREFIX . 'wccf_witness (uid, server, kind, sha256, body, created, '
            . "broken) VALUES ({$uid}, '{$srv}', '{$kind}', '{$sha}', '" . base64_encode($body) . "', {$now}, '"
            . $db->escape_string($broken) . "')");
        if ($db->affected_rows() !== 1) {                                 // the same message again: nothing new
            wccfgame_json(200, ['card_no' => 0, 'why' => 'seen before']);
        }
        $card = $kind === 'rslt' && $broken === '' ? wccfgame_award($uid) : 0;
        if ($card) {
            $db->update_query('wccf_witness', ['card_no' => $card], "uid='{$uid}' AND sha256='{$sha}'");
        }
        $why = $kind !== 'rslt' ? 'before a match' : ($card ? 'a finished match' : ($broken === ''
            ? 'a card less than ' . WCCFGAME_CARD_GAP . ' seconds ago' : 'a match that does not count'));
        wccfgame_json(200, ['card_no' => $card, 'why' => $broken === '' ? $why : "$why - out of line: $broken"]);
    }

    if ($action === 'wccf_club') {                  // the account's latest saved club card ({seq: 0}: none yet)
        $user = wccfgame_token_user();
        $row = wccfgame_club_latest((int) $user['uid']);
        $row = wccfgame_cut_version((int) $user['uid'], $row) ?? $row;   // a cut match: its card, kept here first
        wccfgame_json(200, $row ? ['seq' => (int) $row['seq'], 'sha256' => $row['sha256'], 'card' => $row['card']]
                                : ['seq' => 0]);
    }

    if ($action === 'wccf_club_save') {             // a new version of the account's club card, kept only if it holds
        $user = wccfgame_token_user();
        $uid = (int) $user['uid'];
        $raw = base64_decode($mybb->get_input('card'), true);
        $card = $raw === false ? 'it is not base64' : wccfgame_card_read($raw);
        if (is_string($card)) {
            wccfgame_json(422, ['error' => 'the club card was refused: ' . $card]);
        }
        $sha = hash('sha256', $raw);
        $latest = wccfgame_club_latest($uid);
        if ($latest && $latest['sha256'] === $sha) {                     // sent again (a retry): kept already
            wccfgame_json(200, ['seq' => (int) $latest['seq'], 'sha256' => $sha]);
        }
        if ($mybb->get_input('base') !== ($latest['sha256'] ?? '')) {   // built on another version than the latest
            wccfgame_json(409, ['error' => 'the website has a newer club card - the next start takes it',
                'seq' => (int) ($latest['seq'] ?? 0)]);
        }
        if ($latest) {
            $same = $card['uid'] === $latest['card_uid'] && $card['serial'] === (int) $latest['serial'];
            if ($same && $card['counter'] > (int) $latest['counter']) {
                wccfgame_json(422, ['error' => 'the club card was refused: an older save than the one kept']);
            }
            if (!$same && ((int) $latest['counter'] & 0xFF) > 1) {
                wccfgame_json(422, ['error' => 'the club card was refused: another card - a club moves to a new card '
                    . 'only when its contract has ended']);
            }
        } elseif ($card['uid'] === 'deadbeef' && $card['serial'] === 10000001) {
            // every card older kits made has this id, so it proves nothing: kit 7 makes each online club its own
            wccfgame_json(422, ['error' => 'the club card was refused: it carries the id every older kit card shares - '
                . 'start your online club with kit 7']);
        }
        if (!$latest || $same) {          // what our server saw (a manager transfer's new card: not proven yet - let by)
            $seen = wccfgame_seen($uid);
            if (!$seen) {
                wccfgame_json(422, ['error' => 'the club card was refused: none of our game servers has seen this '
                    . 'account play yet']);
            }
            if (!in_array($card['data'], $seen, true)) {
                wccfgame_json(422, ['error' => 'the club card was refused: it does not match what our game server saw '
                    . 'at the end of your last match']);
            }
        }
        $owned = [];
        $q = $db->simple_select('wccf_owned', 'card_no', "uid='{$uid}'");
        while ($r = $db->fetch_array($q)) {
            $owned[(int) $r['card_no']] = ($owned[(int) $r['card_no']] ?? 0) + 1;
        }
        foreach ($card['players'] as $no) {
            if ($no && ($owned[$no] ?? 0) < 1) {
                wccfgame_json(422, ['error' => "the club card was refused: card $no is registered on it, and your "
                    . 'account does not own it']);
            }
            if ($no) {
                $owned[$no]--;
            }
        }
        if ((int) $db->fetch_field($db->simple_select('wccf_club_versions', 'COUNT(*) AS n',
                "uid='{$uid}' AND created>" . ($now - 60)), 'n') >= WCCFGAME_SAVES_PER_MINUTE) {
            wccfgame_json(429, ['error' => 'too many club card saves in a minute - wait a moment']);
        }
        $seq = ($latest ? (int) $latest['seq'] : 0) + 1;
        $base = $latest ? $latest['sha256'] : '';
        $ip = $db->escape_string(get_ip());
        $db->write_query('INSERT IGNORE INTO ' . TABLE_PREFIX . 'wccf_club_versions (uid, seq, sha256, base, card, '
            . "card_uid, serial, counter, created, ip) VALUES ({$uid}, {$seq}, '{$sha}', '{$base}', '"
            . base64_encode($raw) . "', '{$card['uid']}', {$card['serial']}, {$card['counter']}, {$now}, '{$ip}')");
        if ($db->affected_rows() !== 1) {                                 // another save took this place first
            wccfgame_json(409, ['error' => 'the website has a newer club card - the next start takes it', 'seq' => $seq]);
        }
        wccfgame_json(200, ['seq' => $seq, 'sha256' => $sha]);
    }

    if ($action === 'wccf_formation') {             // the cards on the account's table and where each stands, as the
        $user = wccfgame_token_user();              // kit's board has them: x -1..+1 touchline to touchline, y -1 the
        $uid = (int) $user['uid'];                  // far goal line .. +1 its own, the bench beside the pitch (x 1.24)
        $cards = json_decode($mybb->get_input('cards'), true);
        if (!is_array($cards) || count($cards) > WCCFGAME_TABLE_MAX) {
            wccfgame_json(422, ['error' => 'the table was refused: not a list of at most ' . WCCFGAME_TABLE_MAX . ' cards']);
        }
        $owned = [];
        $q = $db->simple_select('wccf_owned', 'card_no', "uid='{$uid}'");
        while ($r = $db->fetch_array($q)) {
            $owned[(int) $r['card_no']] = ($owned[(int) $r['card_no']] ?? 0) + 1;
        }
        $kept = [];
        foreach ($cards as $c) {
            if (!is_array($c) || count($c) !== 3 || !is_int($c[0] ?? null) || !is_numeric($c[1] ?? null)
                    || !is_numeric($c[2] ?? null) || abs((float) $c[1]) > 1.5 || abs((float) $c[2]) > 1.5) {
                wccfgame_json(422, ['error' => 'the table was refused: each card is [card number, x, y] on the board']);
            }
            if (($owned[$c[0]] ?? 0) < 1) {
                wccfgame_json(422, ['error' => "the table was refused: card {$c[0]} is on it, and your account does "
                    . 'not own it']);
            }
            $owned[$c[0]]--;
            $kept[] = [$c[0], round((float) $c[1], 3), round((float) $c[2], 3)];
        }
        // ponytail: one row per account, replaced - no rate limit; add one if a kit ever sends in a loop
        $db->replace_query('wccf_formations', ['uid' => $uid, 'cards' => $db->escape_string(json_encode($kept)),
            'updated' => $now]);
        wccfgame_json(200, ['kept' => count($kept)]);
    }

    wccfgame_json(404, ['error' => 'unknown action']);
}

// ---- the page the player approves the code on -------------------------------------------------------------------

function wccfgame_output(string $content): void
{
    global $mybb, $headerinclude, $header, $footer;
    $title = 'Link your game';
    add_breadcrumb($title, 'misc.php?action=wccf_link');
    $board = htmlspecialchars_uni($mybb->settings['bbname']);
    output_page("<html>\n<head>\n<title>{$title} - {$board}</title>\n{$headerinclude}\n</head>\n<body>\n{$header}\n"
        . "<table border=\"0\" cellspacing=\"0\" cellpadding=\"5\" class=\"tborder\">\n"
        . "<tr><td class=\"thead\"><strong>{$title}</strong></td></tr>\n"
        . "<tr><td class=\"trow1\">{$content}</td></tr>\n</table>\n{$footer}\n</body>\n</html>");
    exit;
}

function wccfgame_page()
{
    global $mybb, $db;
    if ($mybb->get_input('action') !== 'wccf_link') {
        return;
    }
    $now = TIME_NOW;
    $code = substr(preg_replace('/[^A-Z0-9]/', '', strtoupper($mybb->get_input('code'))), 0, 8);
    $shown = strlen($code) === 8 ? wccfgame_shown($code) : '';

    if (!$mybb->user['uid']) {
        if ($shown !== '') {
            my_setcookie('wccflink', $code, $now + WCCFGAME_CODE_LIFE, true);
        }
        $codeLine = $shown !== '' ? "<p>The code: <strong>{$shown}</strong> - it lasts 10 minutes.</p>\n" : '';
        wccfgame_output("<p>Your game is asking to play online. Log in to WCCF Online, or create an account, to link it.</p>\n"
            . $codeLine
            . "<p><a class=\"button\" href=\"member.php?action=login\">Log In</a> "
            . "<a class=\"button\" href=\"member.php?action=register\">Register</a></p>");
    }
    if (wccfgame_banned($mybb->user)) {
        error_no_permission();
    }
    if ($shown === '') {
        wccfgame_output("<form method=\"get\" action=\"misc.php\">\n<input type=\"hidden\" name=\"action\" value=\"wccf_link\">\n"
            . "<p>Type the code your game shows:</p>\n<p><input type=\"text\" class=\"textbox\" name=\"code\" maxlength=\"9\" "
            . "autocomplete=\"off\"> <input type=\"submit\" class=\"button\" value=\"Continue\"></p>\n</form>");
    }

    $row = $db->fetch_array($db->simple_select('wccf_link', '*', "code='{$code}'", ['limit' => 1]));
    $name = htmlspecialchars_uni($mybb->user['username']);
    $again = '<p>Start again from your game: it will show a new code.</p>';
    if (!$row || ($row['uid'] && (int) $row['uid'] !== (int) $mybb->user['uid'])) {
        wccfgame_output("<p>That code is not valid.</p>\n{$again}");
    }
    if ($row['uid']) {
        my_unsetcookie('wccflink');
        wccfgame_output("<p>Done. Your game is linked to <strong>{$name}</strong> - go back to it; it carries on by itself.</p>");
    }
    if ($row['expires'] < $now) {
        wccfgame_output("<p>That code has run out (they last 10 minutes).</p>\n{$again}");
    }

    if ($mybb->request_method === 'post') {
        verify_post_check($mybb->get_input('my_post_key'));
        $db->update_query('wccf_link', ['uid' => (int) $mybb->user['uid'], 'approved' => $now],
            "lid='" . (int) $row['lid'] . "' AND uid=0 AND expires>={$now}");
        my_unsetcookie('wccflink');
        if ($db->affected_rows() !== 1) {
            wccfgame_output("<p>That code could not be approved.</p>\n{$again}");
        }
        wccfgame_output("<p>Done. Your game is linked to <strong>{$name}</strong> - go back to it; it carries on by itself.</p>");
    }

    wccfgame_output("<p>Your game is asking to play online as <strong>{$name}</strong>.</p>\n"
        . "<p>Code: <strong style=\"font-size:1.6em;letter-spacing:0.15em\">{$shown}</strong></p>\n"
        . "<p>Only approve it if the same code is on your game's screen right now. Never approve a code someone sent you.</p>\n"
        . "<form method=\"post\" action=\"misc.php?action=wccf_link&amp;code={$shown}\">\n"
        . "<input type=\"hidden\" name=\"my_post_key\" value=\"{$mybb->post_code}\">\n"
        . "<input type=\"submit\" class=\"button\" value=\"Approve this game\">\n</form>");
}

// ---- a member who registered from the page goes back to it -------------------------------------------------------

function wccfgame_after_register()
{
    global $mybb;
    $code = substr(preg_replace('/[^A-Z0-9]/', '', strtoupper((string) ($mybb->cookies['wccflink'] ?? ''))), 0, 8);
    if (strlen($code) !== 8 || $mybb->settings['regtype'] !== 'instant') {
        return;
    }
    redirect($mybb->settings['bburl'] . '/misc.php?action=wccf_link&code=' . wccfgame_shown($code),
        'Your account is ready. Now approve your game.');
}
