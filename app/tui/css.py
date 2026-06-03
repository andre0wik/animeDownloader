APP_CSS = """\
SearchScreen {
    layout: vertical;
}
#filters {
    height: auto;
    background: $panel;
    padding: 1 2;
}
.filter-row {
    height: 3;
    margin-bottom: 1;
    align: left middle;
}
.flabel {
    width: 10;
    content-align: right middle;
    padding-right: 1;
}
#genres {
    height: 7;
    border: solid $accent;
}
#btn-row {
    height: 3;
    margin-top: 1;
    align: right middle;
}
#search-status {
    height: 1;
    padding: 0 2;
    content-align: left middle;
}
#results {
    height: 1fr;
    margin-top: 0;
}
AnimeMenuScreen {
    layout: vertical;
}
#series-info {
    height: auto;
    background: $panel;
    padding: 1 2;
}
#ep-list {
    height: 1fr;
    border: solid $accent;
    margin: 0 2;
}
#ep-loading {
    height: 1fr;
}
#ep-actions {
    height: auto;
    padding: 0 2 1 2;
}
.ep-action-row {
    height: 3;
    margin-bottom: 1;
    align: left middle;
}
#sel-count {
    margin-left: 2;
    color: $text-muted;
}
QueueScreen {
    layout: vertical;
}
#queue-summary {
    height: 3;
    background: $panel;
    padding: 1 2;
    content-align: left middle;
}
#queue-table {
    height: 1fr;
}
#queue-actions {
    height: 3;
    padding: 0 2;
    align: left middle;
}
#queue-back {
    dock: right;
}
.dl-status {
    height: 1;
    background: $boost;
    padding: 0 2;
    content-align: left middle;
    color: $text-muted;
}
MainMenuScreen {
    layout: vertical;
    align: center middle;
}
#main-menu {
    width: 60;
    height: auto;
    padding: 2 4;
    background: $panel;
    border: solid $accent;
}
#main-menu Button {
    width: 100%;
    margin-bottom: 1;
}
#main-title {
    text-align: center;
    margin-bottom: 2;
}
MangaSearchScreen {
    layout: vertical;
}
#mg-genres {
    height: 7;
    border: solid $accent;
}
.filter-pair {
    height: 3;
    align: left middle;
}
MangaMenuScreen {
    layout: vertical;
}
SettingsScreen {
    layout: vertical;
    align: center middle;
}
#settings-form {
    width: 72;
    height: auto;
    padding: 2 4;
    background: $panel;
    border: solid $accent;
}
#settings-title {
    text-align: center;
    margin-bottom: 2;
}
.sfield {
    margin-bottom: 1;
}
.sfield Label {
    margin-bottom: 0;
    color: $text-muted;
}
#settings-btns {
    margin-top: 2;
    height: 3;
    align: left middle;
}
#settings-btns Button {
    margin-right: 2;
}
RemoteFileManagerScreen {
    layout: vertical;
}
#fm-diskinfo {
    height: 1;
    background: $boost;
    padding: 0 2;
    content-align: left middle;
}
#fm-path {
    height: 1;
    background: $panel;
    padding: 0 1;
    content-align: left middle;
    color: $text-muted;
}
#fm-table {
    height: 1fr;
}
#fm-actions {
    height: 3;
    background: $panel;
    padding: 0 2;
    align: left middle;
}
#fm-selcount {
    margin-right: 3;
    content-align: left middle;
    width: 20;
}
#fm-actions Button {
    margin-right: 1;
}
EbookSearchScreen {
    layout: vertical;
}
#eb-filters {
    height: auto;
    background: $panel;
    padding: 1 2;
}
#eb-btn-row {
    height: 3;
    margin-top: 1;
    align: right middle;
}
#eb-status {
    height: 1;
    padding: 0 2;
    content-align: left middle;
}
#eb-results {
    height: 1fr;
}
ConfirmModal {
    align: center middle;
}
#confirm-box {
    width: 70;
    height: auto;
    min-height: 8;
    padding: 2 4;
    background: $panel;
    border: solid $error;
}
#confirm-msg {
    margin-bottom: 2;
}
#confirm-btns {
    height: 3;
    align: right middle;
}
#confirm-btns Button {
    margin-left: 2;
}
InputModal {
    align: center middle;
}
#input-box {
    width: 80;
    height: auto;
    padding: 2 4;
    background: $panel;
    border: solid $accent;
}
#input-title {
    margin-bottom: 1;
}
#modal-input {
    margin-bottom: 1;
}
#input-btns {
    height: 3;
    align: right middle;
}
#input-btns Button {
    margin-left: 2;
}
"""
