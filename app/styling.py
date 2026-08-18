"""styling — the whole application's stylesheet, generated from the active skin.

One function, one big f-string. It is long because a desktop application has a
lot of surfaces, but it is all derived from the eleven colours a skin defines,
so switching skin restyles every part of the window at once and nothing is ever
hard-coded to a particular palette.
"""
from core import luminance, mix, readable_on, rgba


def build_css(t, cfg):
    bg, panel, fg = t["BG"], t["PANEL"], t["FG"]
    dim, accent, accent2 = t["DIM"], t["ACCENT"], t["ACCENT2"]
    border, urgent, ok = t["BORDER"], t["URGENT"], t["OK"]
    on_accent = readable_on(accent)
    on_accent2 = readable_on(accent2)
    light = luminance(bg) > 0.5

    head = mix(panel, fg, 0.04) if not light else mix(panel, "#000000", 0.04)
    bar = mix(bg, panel, 0.75)              # activity bar, a shade off the panel
    raised = mix(panel, fg, 0.07)
    sunken = mix(bg, "#000000", 0.25) if not light else mix(bg, "#000000", 0.05)
    ui_font = cfg.get("UI_FONT", "")
    font_rule = "font-family: %s;" % ui_font if ui_font else ""

    return f"""
* {{ outline: none; }}

window.prism, .prism {{
    background: {bg}; color: {fg}; {font_rule}
}}

/* ---- title bar ------------------------------------------------------- */
headerbar.prismhead, .prismhead {{
    background: {head}; border-bottom: 1px solid {border};
    padding: 0 6px; min-height: 38px;
}}
.prismtitle {{ color: {fg}; font-weight: 600; }}
.prismsubtitle {{ color: {dim}; font-size: 11px; }}
.prismhead button, .toolbtn {{
    background: transparent; border: none; color: {dim};
    border-radius: 6px; padding: 2px 8px; min-height: 26px; min-width: 26px;
}}
.prismhead button:hover, .toolbtn:hover {{ background: {raised}; color: {fg}; }}
.toolbtn:checked, .toolbtn.on {{ background: {rgba(accent, 0.22)}; color: {accent}; }}

menubar, .prismmenu {{ background: transparent; color: {fg}; }}
menubar > menuitem {{ padding: 4px 9px; color: {dim}; border-radius: 5px; }}
menubar > menuitem:hover, menubar > menuitem:selected {{
    background: {raised}; color: {fg};
}}
menu, .prismmenu menu, popover, popover.background {{
    background: {panel}; border: 1px solid {border}; border-radius: 8px;
    color: {fg}; padding: 4px;
}}
menu menuitem, popover modelbutton {{
    padding: 5px 12px; border-radius: 5px; color: {fg};
}}
menu menuitem:hover, popover modelbutton:hover {{ background: {accent}; color: {on_accent}; }}
menu separator {{ background: {border}; margin: 4px 2px; }}
menu menuitem:disabled, menu menuitem label:disabled {{ color: {mix(panel, fg, 0.35)}; }}
menu accelerator {{ color: {dim}; }}

/* ---- activity bar ---------------------------------------------------- */
.activitybar {{
    background: {bar}; border-right: 1px solid {border}; padding: 6px 0;
}}
.activitybtn {{
    background: transparent; border: none; color: {mix(bar, fg, 0.55)};
    min-width: 46px; min-height: 42px; padding: 0; border-radius: 0;
    border-left: 2px solid transparent;
}}
.activitybtn:hover {{ color: {fg}; background: {rgba(fg, 0.06)}; }}
.activitybtn:checked {{
    color: {accent}; border-left: 2px solid {accent}; background: {rgba(accent, 0.10)};
}}

/* ---- side bar -------------------------------------------------------- */
.sidebar {{ background: {panel}; }}
.sidehead {{
    padding: 8px 12px 6px 12px; background: {panel};
}}
.sidetitle {{
    color: {dim}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;
}}
.sidebar treeview, .sidebar textview, .sidebar list {{
    background: {panel}; color: {fg};
}}
.sidebar treeview:selected, .sidebar list > row:selected {{
    background: {rgba(accent, 0.26)}; color: {fg};
}}
.sidebar treeview:hover {{ background: {rgba(fg, 0.05)}; }}
.sidebar scrollbar {{ background: transparent; }}
.sideempty {{ color: {dim}; font-size: 12px; }}
.sidebtn {{
    background: {raised}; color: {fg}; border: 1px solid {border};
    border-radius: 7px; padding: 6px 12px;
}}
.sidebtn:hover {{ background: {mix(raised, fg, 0.10)}; border-color: {accent}; }}
.recentlink {{
    background: transparent; border: none; color: {accent};
    padding: 2px 4px; font-size: 12px;
}}
.recentlink:hover {{ color: {fg}; }}

/* ---- editor tabs ----------------------------------------------------- */
.edtabs {{ background: {head}; }}
.edtab {{
    background: {mix(head, bg, 0.5)}; border-right: 1px solid {border};
    border-top: 2px solid transparent; padding: 5px 6px 5px 12px; color: {dim};
}}
.edtab:hover {{ background: {mix(head, fg, 0.06)}; }}
.edtab.active {{
    background: {bg}; color: {fg}; border-top: 2px solid {accent};
}}
.edtab label {{ color: inherit; }}
.edtabclose {{
    color: {dim}; background: transparent; border: none;
    min-width: 18px; min-height: 18px; padding: 0; border-radius: 9px;
}}
.edtabclose:hover {{ background: {rgba(urgent, 0.22)}; color: {urgent}; }}
.editorhead {{ background: {head}; border-bottom: 1px solid {border}; }}

/* ---- the editor itself ------------------------------------------------ */
.codeeditor, .codeeditor text {{ background: {bg}; color: {fg}; }}
.codeeditor border {{ background: {bg}; color: {mix(bg, fg, 0.35)}; }}
scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{
    background: {mix(bg, fg, 0.22)}; border-radius: 6px; min-width: 8px; min-height: 8px;
}}
scrollbar slider:hover {{ background: {mix(bg, fg, 0.38)}; }}

paned > separator {{
    background: {border}; min-width: 4px; min-height: 4px;
}}
paned > separator:hover {{ background: {accent}; }}

/* ---- find and the edit bar -------------------------------------------- */
.editorfind {{ background: {head}; border-bottom: 1px solid {border}; padding: 5px 8px; }}
.editorfind entry, .prism entry {{
    background: {sunken}; color: {fg}; border: 1px solid {border};
    border-radius: 6px; padding: 3px 9px;
}}
.prism entry:focus {{ border-color: {accent}; }}
.findtoggle {{
    background: transparent; color: {dim}; border: 1px solid {border};
    border-radius: 6px; padding: 0 8px; min-height: 24px;
}}
.findtoggle:checked {{ background: {accent}; color: {on_accent}; }}
.findstatus {{ color: {dim}; font-size: 11px; }}

.editbar {{
    background: {mix(head, accent, 0.12)}; border-bottom: 1px solid {accent};
    padding: 6px 8px;
}}
.editbartag {{
    color: {on_accent}; background: {accent}; font-size: 10px; font-weight: 700;
    letter-spacing: 1px; padding: 2px 8px; border-radius: 5px;
}}
.editbarnote {{ color: {dim}; font-size: 11px; padding: 0 4px; }}
.editbargo {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 6px; padding: 2px 12px; font-weight: 600;
}}
.editbargo:hover {{ background: {mix(accent, fg, 0.18)}; }}
.editbargo:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.iconbtn {{
    background: transparent; border: none; color: {dim};
    border-radius: 6px; padding: 0 6px; min-height: 24px; min-width: 24px;
}}
.iconbtn:hover {{ background: {raised}; color: {fg}; }}

/* ---- the run bar ------------------------------------------------------ */
.runbar {{ background: {head}; border-bottom: 1px solid {border}; padding: 5px 10px; }}
.runbtn-main {{
    background: {ok}; color: {readable_on(ok)}; border: none;
    border-radius: 6px; padding: 3px 14px; font-weight: 700;
}}
.runbtn-main:hover {{ background: {mix(ok, fg, 0.20)}; }}
.runbtn-main:disabled {{ background: {mix(panel, fg, 0.12)}; color: {dim}; }}
.runbar combobox button {{
    background: {sunken}; color: {fg}; border: 1px solid {border};
    border-radius: 6px; padding: 1px 8px; min-height: 24px;
}}
.runsummary {{ color: {accent}; font-size: 11px; font-weight: 600; padding: 0 4px; }}
.runstate {{ color: {dim}; font-size: 11px; padding: 0 6px; }}
.runinstall {{
    background: {accent2}; color: {readable_on(accent2)}; border: none;
    border-radius: 6px; padding: 2px 12px; font-weight: 600;
}}
.runinstall:hover {{ background: {mix(accent2, fg, 0.18)}; }}
.runopen {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 6px; padding: 2px 12px; font-weight: 600;
}}
.runopen:hover {{ background: {mix(accent, fg, 0.18)}; }}

/* ---- bottom panel ----------------------------------------------------- */
.panelhead {{
    background: {head}; border-top: 1px solid {border};
    border-bottom: 1px solid {border}; padding: 0 4px 0 10px;
}}
.paneltab {{
    background: transparent; border: none; color: {dim};
    padding: 5px 10px; border-bottom: 2px solid transparent; border-radius: 0;
    font-size: 11px; font-weight: 600; letter-spacing: 0.8px;
}}
.paneltab:hover {{ color: {fg}; }}
.paneltab:checked {{ color: {fg}; border-bottom: 2px solid {accent}; }}
.termpick {{ color: {dim}; font-size: 11px; }}
.outputview, .outputview text {{ background: {bg}; color: {fg}; }}

/* ---- the assistant ---------------------------------------------------- */
.assistpane {{ background: {panel}; border-left: 1px solid {border}; }}
.assisthead {{
    background: {head}; border-bottom: 1px solid {border}; padding: 4px 6px 4px 12px;
}}
.assistlabel {{
    color: {dim}; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;
}}
.assisthint {{ color: {accent}; font-size: 11px; }}

/* ---- status bar ------------------------------------------------------- */
.statusbar {{
    background: {mix(panel, accent, 0.12)}; border-top: 1px solid {border};
    padding: 2px 10px; min-height: 22px;
}}
.statusitem {{ color: {mix(panel, fg, 0.72)}; font-size: 11px; }}
.statusbtn {{
    color: {mix(panel, fg, 0.72)}; font-size: 11px; padding: 0 7px; border: none;
    background: transparent; border-radius: 5px; min-height: 18px;
}}
.statusbtn:hover {{ background: {rgba(fg, 0.14)}; color: {fg}; }}
.statusbad {{ color: {urgent}; font-size: 11px; }}
.statusgood {{ color: {ok}; font-size: 11px; }}

/* ---- source control ----------------------------------------------------- */
.gitbranch {{
    background: {raised}; color: {fg}; border: 1px solid {border};
    border-radius: 7px; padding: 3px 10px; font-size: 12px;
}}
.gitbranch:hover {{ border-color: {accent}; }}
.gitsync {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 7px; padding: 3px 10px; font-size: 12px; font-weight: 600;
}}
.gitsync:hover {{ background: {mix(accent, fg, 0.18)}; }}
.gitsync:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.gitmessage, .gitmessage text {{
    background: {sunken}; color: {fg}; padding: 6px 8px;
}}
.gitcommit {{
    background: {ok}; color: {readable_on(ok)}; border: none;
    border-radius: 7px; padding: 5px 12px; font-weight: 700;
}}
.gitcommit:hover {{ background: {mix(ok, fg, 0.18)}; }}
.gitcommit:disabled {{ background: {mix(panel, fg, 0.12)}; color: {dim}; }}
.gitrow {{ padding: 2px 2px 2px 4px; border-radius: 5px; }}
.gitrow:hover {{ background: {mix(panel, fg, 0.09)}; }}
.gitname {{ color: {fg}; font-size: 12px; }}
.gitfolder {{ color: {dim}; font-size: 11px; }}
.gitmod {{ color: {accent2}; font-weight: 700; font-family: monospace; }}
.gitadd {{ color: {ok}; font-weight: 700; font-family: monospace; }}
.gitdel {{ color: {urgent}; font-weight: 700; font-family: monospace; }}
.gitnew {{ color: {ok}; font-weight: 700; font-family: monospace; }}
.gitconflict {{ color: {urgent}; font-weight: 700; font-family: monospace; }}

/* ---- the selection popup ----------------------------------------------- */
.selbar, .selbar > contents {{
    background: {raised}; border: 1px solid {border}; border-radius: 9px;
    padding: 0;
}}
.selbtn {{
    background: transparent; border: none; color: {fg};
    padding: 3px 11px; border-radius: 6px; font-size: 12px;
}}
.selbtn:hover {{ background: {accent}; color: {on_accent}; }}

/* ---- command palette --------------------------------------------------- */
.palette {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
.palette entry {{
    background: {sunken}; color: {fg}; border: 1px solid {border};
    border-radius: 7px; padding: 6px 10px; font-size: 13px;
}}
.palette entry:focus {{ border-color: {accent}; }}
.palette scrolledwindow, .palette list, .palette viewport {{
    background: {panel}; border: none;
}}
.palette list > row {{ background: transparent; }}
.palette list > row:hover {{ background: {mix(panel, fg, 0.10)}; }}
.palette list > row:selected {{ background: {accent}; }}
.palette list > row:selected label {{ color: {on_accent}; }}
.paletterow {{ padding: 5px 10px; border-radius: 6px; }}
.palettelabel {{ color: {fg}; }}
.palettekeys {{ color: {dim}; font-size: 11px; font-family: monospace; }}
.palettefrom {{ color: {accent}; font-size: 10px; letter-spacing: 0.6px; }}

/* ---- search results ---------------------------------------------------- */
.searchhit {{ padding: 3px 10px; border-radius: 5px; }}
.searchfile {{ color: {accent}; font-size: 11px; font-weight: 600; }}
.searchline {{ color: {dim}; font-family: monospace; font-size: 11px; }}
.searchtext {{ color: {fg}; font-family: monospace; font-size: 11px; }}
.searchcount {{ color: {dim}; font-size: 11px; }}

/* ---- extensions -------------------------------------------------------- */
.extrow {{
    background: {mix(panel, fg, 0.05)}; border: 1px solid {border};
    border-radius: 8px; padding: 9px 12px; margin-bottom: 6px;
}}
.extname {{ color: {fg}; font-weight: 600; }}
.extblurb {{ color: {dim}; font-size: 11px; }}
.extbad {{ color: {urgent}; font-size: 11px; font-family: monospace; }}

/* ---- welcome ----------------------------------------------------------- */
.welcome {{ background: {bg}; }}
.welcomemark {{ color: {accent}; font-weight: 700; }}
.welcometitle {{ color: {fg}; }}
.welcomesub {{ color: {dim}; }}
.welcomerow {{ color: {dim}; font-size: 12px; }}
.welcomekey {{ color: {fg}; font-family: monospace; }}
.welcomeinvite {{ color: {accent}; font-size: 12px; }}

/* ---- preferences ------------------------------------------------------- */
.prefs {{ background: {bg}; color: {fg}; }}
.prefs notebook {{ background: {bg}; }}
.prefs notebook header {{ background: {head}; border-bottom: 1px solid {border}; }}
.prefs notebook tab {{ padding: 6px 12px; color: {dim}; }}
.prefs notebook tab:checked {{ color: {fg}; box-shadow: inset 0 -2px {accent}; }}
.heading {{ color: {fg}; font-weight: 700; margin-top: 8px; }}
.hint {{ color: {dim}; font-size: 11px; }}
.prefs button {{
    background: {raised}; color: {fg}; border: 1px solid {border};
    border-radius: 6px; padding: 3px 10px;
}}
.prefs button:hover {{ border-color: {accent}; }}
.prefs button:disabled {{ color: {dim}; border-color: {border}; }}
/* Without these, every text box in every dialog arrives Adwaita-white. */
.prefs entry {{
    background: {sunken}; color: {fg}; border: 1px solid {border};
    border-radius: 6px; padding: 5px 8px; caret-color: {fg};
}}
.prefs entry:focus {{ border-color: {accent}; }}
.prefs entry selection {{ background: {accent}; color: {on_accent}; }}
.prefs entry image {{ color: {dim}; }}
.prefs combobox button {{ background: {raised}; color: {fg}; }}
.prefs checkbutton {{ color: {fg}; }}
.prefs scrolledwindow, .prefs viewport, .prefs list {{ background: {bg}; }}
/* Where there is no window manager to draw one, GTK draws its own
   title bar and it arrives Adwaita-white. */
.prefs headerbar, .prefs .titlebar {{
    background: {head}; color: {fg}; border-bottom: 1px solid {border};
}}

/* ---- github ------------------------------------------------------------ */
.ghbar {{
    background: {head}; border: 1px solid {border}; border-radius: 8px;
    padding: 11px 13px;
}}
.ghlist {{ background: {sunken}; }}
.ghlist row {{ border-bottom: 1px solid {border}; }}
.ghlist row:selected {{ background: {raised}; }}
.ghname {{ color: {fg}; font-weight: 700; }}
.ghtag {{
    background: {raised}; color: {dim}; font-size: 10px; border-radius: 4px;
    padding: 0 6px;
}}
.ghkey {{ color: {dim}; font-family: monospace; font-size: 11px; }}
.devicecode {{
    color: {accent}; font-family: monospace; font-size: 30px;
    font-weight: 700; letter-spacing: 3px;
}}

/* ---- the update card --------------------------------------------------- */
.whatsnew {{ background: {bg}; }}
.wnhead {{ background: {head}; border-bottom: 1px solid {border}; }}
.wntitle {{ color: {fg}; font-size: 17px; font-weight: 700; }}
.wnsub {{ color: {dim}; font-size: 11px; }}
.wnflag {{
    background: {accent2}; color: {on_accent2}; font-size: 11px;
    font-weight: 700;
    padding: 4px 20px;
}}
.wnnotes {{ background: {bg}; }}
.wnbullet {{ color: {accent}; }}
.wnnote {{ color: {fg}; font-size: 12px; }}
/* `.prefs button` is class+element, so a bare `.wnbtn` loses to it. These
   selectors have to outrank it or the buttons stay the preferences grey. */
.wnactions {{
    background: {head}; border-top: 1px solid {border}; padding: 12px 16px;
}}
.whatsnew button.wnbtn {{
    background: {raised}; color: {fg}; border: 1px solid {border};
    border-radius: 6px; padding: 6px 15px; font-size: 12px;
}}
.whatsnew button.wnbtn:hover {{ border-color: {accent}; background: {panel}; }}
.whatsnew button.wnprimary {{
    background: {accent}; color: {on_accent}; border-color: {accent};
    font-weight: 700;
}}
.whatsnew button.wnprimary:disabled {{
    background: {raised}; color: {dim}; border-color: {border};
}}
.whatsnew button.wnprimary:hover {{
    background: {accent}; border-color: {fg}; color: {on_accent};
}}
.wncmd {{
    background: {raised}; color: {dim}; font-family: monospace; font-size: 11px;
    padding: 9px 20px; border-top: 1px solid {border};
}}
"""
