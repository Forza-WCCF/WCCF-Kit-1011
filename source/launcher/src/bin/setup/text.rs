//! SETUP.exe's words: English, or Italian or Japanese when Windows' display language is one of those.  The kit's
//! scripts (their output in the window) stay in English.

use windows_sys::Win32::Globalization::GetUserDefaultUILanguage;

pub struct Text {
    pub title: &'static str,
    pub intro: &'static str,
    pub game_folder: &'static str,
    pub browse: &'static str,
    pub browse_title: &'static str,
    pub set_up: &'static str,
    pub undo: &'static str,
    pub undo_confirm: &'static str,
    pub no_folder: &'static str,
    pub game_text: &'static str,
    pub english: &'static str,
    pub japanese: &'static str,
    pub english_is_on: &'static str,
    pub japanese_is_on: &'static str,
    pub update_heading: &'static str,
    pub not_known: &'static str,
    pub update: &'static str,
    pub whats_new: &'static str,
    pub release: &'static str,
    pub test_build: &'static str,
    pub this_kit: &'static str,
    pub asking: &'static str,
    pub pick: &'static str,
    pub none_listed: &'static str,
    pub no_answer: &'static str,
    pub retry: &'static str,
    pub confirm_release: &'static str,
    pub confirm_test: &'static str,
    pub downloading: &'static str,
    pub unzipping: &'static str,
    pub copying: &'static str,
    pub updated: &'static str,
    pub after_update: &'static str,
    pub after_update_english: &'static str,
    pub close_game: &'static str,
    pub download_failed: &'static str,
    pub unzip_failed: &'static str,
    pub not_a_kit: &'static str,
    pub write_failed: &'static str,
    pub done: &'static str,
    pub failed: &'static str,
    pub busy: &'static str,
}

const EN: Text = Text {
    title: "WCCF kit - setup",
    intro: "Sets up the game folder for the kit, chooses the game's language and updates the kit. Close the game first.",
    game_folder: "Game folder:",
    browse: "Browse...",
    browse_title: "Pick the game folder (the one with client_Release.exe)",
    set_up: "Set up / repair",
    undo: "Undo setup",
    undo_confirm: "Put the game folder back the way it was before setup?",
    no_folder: "Pick the game folder first (the one with client_Release.exe).",
    game_text: "Game language:",
    english: "English",
    japanese: "Japanese",
    english_is_on: "Now: English",
    japanese_is_on: "Now: Japanese (Sega's own)",
    update_heading: "Update the kit - this kit: {}",
    not_known: "not known",
    update: "UPDATE",
    whats_new: "What's new",
    release: "release",
    test_build: "test build",
    this_kit: "(this kit)",
    asking: "Asking GitHub for the kit's releases ...",
    pick: "Pick a kit, then UPDATE. \"What's new\" opens its page.",
    none_listed: "GitHub lists no kit ZIP.",
    no_answer: "GitHub did not answer: {}",
    retry: "Close SETUP and start it again to retry.",
    confirm_release: "Put the release {} into this kit folder?\n\nYour club cards, keys and settings (data) are kept. \
                      Close the game first.",
    confirm_test: "Put the test build {} into this kit folder?\n\nYour club cards, keys and settings (data) are kept. \
                   Close the game first.",
    downloading: "Downloading {} ...",
    unzipping: "Unzipping ...",
    copying: "Copying {} into the kit folder ...",
    updated: "This kit folder now holds {}.",
    after_update: "The kit is updated.\n\nSet up the game folder for the new kit now?",
    after_update_english: "The kit is updated.\n\nSet up the game folder for the new kit now, and put its English in?",
    close_game: "Close the game first: {} runs from the kit folder.",
    download_failed: "The download failed: {}",
    unzip_failed: "The ZIP did not unzip: {}",
    not_a_kit: "This ZIP is not a kit: no folder in it holds PLAY.exe.",
    write_failed: "{}: could not write it ({}) - close the game and update again.",
    done: "Done.",
    failed: "Failed - the output below says why.",
    busy: "Wait: SETUP is busy.",
};

const IT: Text = Text {
    title: "Kit WCCF - configurazione",
    intro: "Configura la cartella del gioco per il kit, sceglie la lingua del gioco e aggiorna il kit. Chiudi prima il \
            gioco.",
    game_folder: "Cartella del gioco:",
    browse: "Sfoglia...",
    browse_title: "Scegli la cartella del gioco (quella con client_Release.exe)",
    set_up: "Configura / ripara",
    undo: "Annulla configurazione",
    undo_confirm: "Riportare la cartella del gioco com'era prima della configurazione?",
    no_folder: "Scegli prima la cartella del gioco (quella con client_Release.exe).",
    game_text: "Lingua del gioco:",
    english: "Inglese",
    japanese: "Giapponese",
    english_is_on: "Ora: inglese",
    japanese_is_on: "Ora: giapponese (originale Sega)",
    update_heading: "Aggiorna il kit - questo kit: {}",
    not_known: "sconosciuto",
    update: "AGGIORNA",
    whats_new: "Novità",
    release: "versione",
    test_build: "prova",
    this_kit: "(questo kit)",
    asking: "Richiesta a GitHub delle versioni del kit ...",
    pick: "Scegli un kit, poi AGGIORNA. \"Novità\" apre la sua pagina.",
    none_listed: "GitHub non elenca nessuno ZIP del kit.",
    no_answer: "GitHub non ha risposto: {}",
    retry: "Chiudi SETUP e riavvialo per riprovare.",
    confirm_release: "Mettere la versione {} in questa cartella del kit?\n\nLe tue carte club, i tasti e le \
                      impostazioni (data) restano. Chiudi prima il gioco.",
    confirm_test: "Mettere la versione di prova {} in questa cartella del kit?\n\nLe tue carte club, i tasti e le \
                   impostazioni (data) restano. Chiudi prima il gioco.",
    downloading: "Download di {} ...",
    unzipping: "Estrazione ...",
    copying: "Copia di {} nella cartella del kit ...",
    updated: "Questa cartella del kit ora contiene {}.",
    after_update: "Il kit è aggiornato.\n\nConfigurare ora la cartella del gioco per il nuovo kit?",
    after_update_english: "Il kit è aggiornato.\n\nConfigurare ora la cartella del gioco per il nuovo kit e rimettere \
                           l'inglese?",
    close_game: "Chiudi prima il gioco: {} è in esecuzione dalla cartella del kit.",
    download_failed: "Download non riuscito: {}",
    unzip_failed: "Impossibile estrarre lo ZIP: {}",
    not_a_kit: "Questo ZIP non è un kit: nessuna sua cartella contiene PLAY.exe.",
    write_failed: "{}: scrittura non riuscita ({}) - chiudi il gioco e aggiorna di nuovo.",
    done: "Fatto.",
    failed: "Non riuscito - il motivo è nel testo qui sotto.",
    busy: "Attendi: SETUP è occupato.",
};

const JA: Text = Text {
    title: "WCCF キット - セットアップ",
    intro: "キット用のゲームフォルダーのセットアップ、ゲームの言語の切り替え、キットの更新を行います。先にゲームを閉じてください。",
    game_folder: "ゲームフォルダー:",
    browse: "参照...",
    browse_title: "ゲームフォルダー（client_Release.exe があるフォルダー）を選んでください",
    set_up: "セットアップ / 修復",
    undo: "セットアップを元に戻す",
    undo_confirm: "ゲームフォルダーをセットアップ前の状態に戻しますか？",
    no_folder: "先にゲームフォルダー（client_Release.exe があるフォルダー）を選んでください。",
    game_text: "ゲームの言語:",
    english: "英語",
    japanese: "日本語",
    english_is_on: "現在: 英語",
    japanese_is_on: "現在: 日本語（セガのオリジナル）",
    update_heading: "キットの更新 - このキット: {}",
    not_known: "不明",
    update: "更新",
    whats_new: "変更内容",
    release: "リリース",
    test_build: "テスト版",
    this_kit: "（このキット）",
    asking: "GitHub からキットのリリース一覧を取得しています...",
    pick: "キットを選んで「更新」を押してください。「変更内容」でそのページを開きます。",
    none_listed: "GitHub にキットの ZIP がありません。",
    no_answer: "GitHub から応答がありません: {}",
    retry: "SETUP を閉じて、もう一度起動してください。",
    confirm_release: "リリース {} をこのキットフォルダーに入れますか？\n\nクラブカード、キー、設定（data）はそのまま残ります。\
                      先にゲームを閉じてください。",
    confirm_test: "テスト版 {} をこのキットフォルダーに入れますか？\n\nクラブカード、キー、設定（data）はそのまま残ります。\
                   先にゲームを閉じてください。",
    downloading: "{} をダウンロードしています...",
    unzipping: "展開しています...",
    copying: "{} をキットフォルダーにコピーしています...",
    updated: "このキットフォルダーは {} になりました。",
    after_update: "キットを更新しました。\n\n新しいキット用にゲームフォルダーをセットアップしますか？",
    after_update_english: "キットを更新しました。\n\n新しいキット用にゲームフォルダーをセットアップし、英語化もやり直しますか？",
    close_game: "先にゲームを閉じてください: {} がキットフォルダーから実行されています。",
    download_failed: "ダウンロードに失敗しました: {}",
    unzip_failed: "ZIP を展開できませんでした: {}",
    not_a_kit: "この ZIP はキットではありません（PLAY.exe を含むフォルダーがありません）。",
    write_failed: "{} に書き込めませんでした（{}）。ゲームを閉じて、もう一度更新してください。",
    done: "完了しました。",
    failed: "失敗しました（理由は下の表示にあります）。",
    busy: "処理中です。終わるまでお待ちください。",
};

/// The words for Windows' display language: LANG_ITALIAN 0x10, LANG_JAPANESE 0x11, else English.  WCCF_KIT_LANG=it,
/// ja or en picks one (to check a translation on any PC).
pub fn t() -> &'static Text {
    // SAFETY: a plain query without arguments.
    let windows = unsafe { GetUserDefaultUILanguage() } & 0x3ff;
    match std::env::var("WCCF_KIT_LANG").as_deref() {
        Ok("it") => &IT,
        Ok("ja") => &JA,
        Ok("en") => &EN,
        _ if windows == 0x10 => &IT,
        _ if windows == 0x11 => &JA,
        _ => &EN,
    }
}

/// `text` with each "{}" filled, in order.
pub fn fill(text: &str, args: &[&str]) -> String {
    let mut out = String::new();
    let mut parts = text.split("{}");
    out.push_str(parts.next().unwrap_or(""));
    for (i, part) in parts.enumerate() {
        out.push_str(args.get(i).copied().unwrap_or(""));
        out.push_str(part);
    }
    out
}
