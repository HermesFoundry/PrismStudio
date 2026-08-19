"""styling — the whole application's stylesheet, generated from the active skin.

One function, one big f-string. It is long because a desktop application has a
lot of surfaces, but it is all derived from the eleven colours a skin defines,
so switching skin restyles every part of the window at once and nothing is ever
hard-coded to a particular palette.

Two rules keep it from turning back into a pile of slabs:

*Two surfaces.* Everything that is chrome — title bar, activity bar, side bar,
tab strip, panel header, status bar — is the one panel colour. The canvas the
editor and terminals draw on is the background colour. A seam only appears
where those two meet, so the window reads as one sheet with a hole cut in it
for your code rather than as six stacked bars in six shades of grey.

*One type ramp.* 13px for anything you read, 11px for anything you glance at,
10px for the small capitals that name a region. Nothing else. GTK's default UI
font is a size or two larger than an editor wants, which is most of what makes
an unstyled window feel bulky.
"""
from core import luminance, mix, readable_on, rgba

# the type ramp, in one place, because half of "bulky" is just font size
BODY = 13
SMALL = 11
MICRO = 10


def build_css(t, cfg):
    bg, panel, fg = t["BG"], t["PANEL"], t["FG"]
    dim, accent, accent2 = t["DIM"], t["ACCENT"], t["ACCENT2"]
    border, urgent, ok = t["BORDER"], t["URGENT"], t["OK"]
    on_accent = readable_on(accent)
    on_accent2 = readable_on(accent2)
    light = luminance(bg) > 0.5

    # A skin may name its surfaces; where it does not, they are mixed out of
    # the two it does have. Naming them is how a palette copied from somewhere
    # else stays exactly what it was copied from.
    def skin(key, fallback):
        return t.get(key) or fallback

    head = skin("SURFACE_TITLE", panel)          # title bar
    bar = skin("SURFACE_ACTIVITY", panel)        # activity rail
    strip = skin("SURFACE_TABS", panel)          # the tab strip behind the tabs
    tab_idle = skin("SURFACE_TAB", panel)        # a tab you are not on
    status_bg = skin("SURFACE_STATUS", panel)
    status_fg = skin("STATUS_FG", mix(panel, fg, 0.62))
    menu_bg = skin("MENU_BG", panel)
    menu_pick = skin("MENU_SELECT", accent)
    hover = skin("HOVER_BG", rgba(fg, 0.06))
    picked = skin("SELECT_BG", rgba(accent, 0.22))
    picked_idle = skin("SELECT_IDLE_BG", rgba(fg, 0.10))
    focus_ring = skin("FOCUS_BORDER", accent)
    button_bg = skin("BUTTON_BG", accent)
    button_hover = skin("BUTTON_HOVER", mix(accent, fg, 0.18))
    # The slider is translucent so the code shows through it, the way it does
    # in the window this palette came from.
    slider = rgba(skin("SCROLL_SLIDER", mix(bg, fg, 0.55)), 0.40)
    slider_hot = rgba(skin("SCROLL_SLIDER", mix(bg, fg, 0.55)), 0.65)

    raised = skin("SURFACE_RAISED",
                  mix(panel, fg, 0.09) if not light else mix(panel, "#000000", 0.07))
    sunken = skin("SURFACE_INPUT",
                  mix(bg, "#000000", 0.25) if not light else mix(bg, "#000000", 0.05))
    # a hairline inside the chrome: present, but never the loudest thing in view
    line = skin("SURFACE_LINE",
                mix(panel, fg, 0.13) if not light else mix(panel, "#000000", 0.13))
    ui_font = cfg.get("UI_FONT", "")
    font_rule = "font-family: %s;" % ui_font if ui_font else ""


    return f"""
* {{ outline: none; }}

/* Everything that answers to the pointer fades rather than snaps. */
button, .toolbtn, .iconbtn, .edtab, .activitybtn, .paneltab, .statusbtn,
.sidebtn, menuitem, .palette list > row {{
    transition: background-color 90ms ease-out, color 90ms ease-out,
                border-color 90ms ease-out, opacity 90ms ease-out;
}}

window.prism, .prism {{
    background: {bg}; color: {fg}; {font_rule} font-size: {BODY}px;
}}

/* ---- title bar ------------------------------------------------------- */
headerbar.prismhead, .prismhead {{
    background: {head}; border-bottom: none;
    padding: 0 4px; min-height: 30px;
}}
.prismtitle {{ color: {fg}; font-weight: 400; font-size: {SMALL}px; }}
.prismsubtitle {{ color: {mix(head, fg, 0.55)}; font-size: {SMALL}px; }}
.prismhead button, .toolbtn {{
    background: transparent; border: none; color: {mix(head, fg, 0.82)};
    border-radius: 3px; padding: 1px 6px; min-height: 22px; min-width: 22px;
}}
.prismhead button:hover, .toolbtn:hover {{
    background: {rgba(fg, 0.10)}; color: {t.get("ACTIVE_FG", fg)};
}}
.toolbtn:checked, .toolbtn.on {{ background: {rgba(fg, 0.16)}; color: {t.get("ACTIVE_FG", fg)}; }}

/* The menu bar is where it is in every editor of this shape: in the title
   bar, on the left, one word each. */
menubar, .prismmenu {{ background: transparent; color: {fg}; }}
menubar > menuitem {{
    padding: 3px 8px; color: {mix(head, fg, 0.86)}; border-radius: 3px;
    font-size: {SMALL}px;
}}
menubar > menuitem:hover, menubar > menuitem:selected {{
    background: {rgba(fg, 0.12)}; color: {t.get("ACTIVE_FG", fg)};
}}
menu, .prismmenu menu, popover, popover.background {{
    background: {menu_bg}; border: 1px solid {mix(menu_bg, fg, 0.20)};
    border-radius: 3px; color: {fg}; padding: 4px 0; font-size: {BODY}px;
}}
menu menuitem, popover modelbutton {{
    padding: 3px 26px 3px 14px; border-radius: 0; color: {fg};
}}
menu menuitem:hover, popover modelbutton:hover {{
    background: {menu_pick}; color: {t.get("ACTIVE_FG", fg)};
}}
menu separator {{ background: {mix(menu_bg, fg, 0.18)}; margin: 4px 0; }}
menu menuitem:disabled, menu menuitem label:disabled {{ color: {mix(menu_bg, fg, 0.35)}; }}
menu accelerator {{ color: {mix(menu_bg, fg, 0.55)}; }}

/* ---- activity bar ---------------------------------------------------- */
.activitybar {{ background: {bar}; padding: 0; }}
.activitybtn {{
    background: transparent; border: none; color: {mix(bar, fg, 0.62)};
    min-width: 48px; min-height: 48px; padding: 0; border-radius: 0;
    border-left: 2px solid transparent;
}}
.activitybtn:hover {{ color: {t.get("ACTIVE_FG", fg)}; background: transparent; }}
.activitybtn:checked {{
    color: {t.get("ACTIVE_FG", fg)}; border-left: 2px solid {t.get("ACTIVE_FG", fg)};
    background: transparent;
}}

/* ---- side bar -------------------------------------------------------- */
.sidebar {{ background: {panel}; }}
.sidehead {{ padding: 8px 8px 6px 20px; background: {panel}; }}
.sidetitle {{
    color: {mix(panel, fg, 0.92)}; font-size: {SMALL}px; font-weight: 400;
    letter-spacing: 0.4px;
}}
.sidesectionrow {{
    background: {mix(panel, fg, 0.06)}; padding: 3px 8px 3px 8px;
    border-top: 1px solid {mix(panel, "#000000", 0.35)};
}}
.sidesection {{
    color: {mix(panel, fg, 0.92)}; font-size: {SMALL}px; font-weight: 700;
}}
.sidechevron {{ color: {mix(panel, fg, 0.75)}; font-size: {SMALL}px; }}
.sidebar treeview, .sidebar textview, .sidebar list {{
    background: {panel}; color: {fg};
}}
.sidebar treeview {{ font-size: {BODY}px; }}
.sidebar treeview:selected, .sidebar list > row:selected {{
    background: {picked}; color: {t.get("ACTIVE_FG", fg)};
}}
.sidebar treeview:hover, .sidebar list > row:hover {{ background: {hover}; }}
.sidebar scrollbar {{ background: transparent; }}
.sideempty {{ color: {mix(panel, fg, 0.60)}; font-size: {BODY}px; }}
.sidebtn {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 5px 12px; font-size: {BODY}px;
}}
.sidebtn:hover {{ background: {button_hover}; }}
.recentlink {{
    background: transparent; border: none; color: {mix(panel, accent, 0.85)};
    padding: 1px 4px; font-size: {BODY}px;
}}
.recentlink:hover {{ color: {t.get("ACTIVE_FG", fg)}; }}

/* ---- editor tabs ----------------------------------------------------- */
/* Square tabs on a strip of their own colour, the one you are on cut out of
   the editor and marked along the top. */
.edtabs {{ background: {strip}; }}
.editorhead {{ background: {strip}; padding: 0 4px 0 0; }}
.edtab {{
    background: {tab_idle}; border-top: 1px solid transparent;
    border-right: 1px solid {strip};
    padding: 0 6px 0 12px; color: {mix(tab_idle, fg, 0.72)}; min-height: 35px;
}}
.edtab:hover {{ background: {mix(tab_idle, fg, 0.06)}; }}
.edtab.active {{
    background: {bg}; color: {t.get("ACTIVE_FG", fg)};
    border-top: 1px solid {accent};
}}
.edtab label {{ color: inherit; font-size: {BODY}px; }}
.edtabclose {{
    color: {fg}; background: transparent; border: none; opacity: 0;
    min-width: 20px; min-height: 20px; padding: 0; border-radius: 3px;
}}
.edtab.active .edtabclose, .edtab:hover .edtabclose {{ opacity: 0.8; }}
.edtabclose:hover {{ background: {rgba(fg, 0.16)}; color: {fg}; opacity: 1; }}

.minimap {{ background: {bg}; }}

/* ---- breadcrumbs ------------------------------------------------------ */
.breadcrumbs {{ background: {bg}; padding: 1px 18px; min-height: 22px; }}
.crumb {{
    background: transparent; border: none; padding: 0 4px;
    color: {mix(bg, fg, 0.72)}; font-size: {SMALL}px;
}}
.crumb:hover {{ color: {t.get("ACTIVE_FG", fg)}; background: transparent; }}
.crumbsep {{ color: {mix(bg, fg, 0.45)}; font-size: {SMALL}px; }}

/* ---- the editor itself ------------------------------------------------ */
.codeeditor, .codeeditor text {{ background: {bg}; color: {fg}; }}
.codeeditor border {{ background: {bg}; color: {skin("LINE_NUMBER", mix(bg, fg, 0.30))}; }}
scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{
    background: {slider}; border-radius: 0; min-width: 10px; min-height: 10px;
    border: 2px solid transparent; background-clip: padding-box;
}}
scrollbar slider:hover {{ background: {slider_hot}; background-clip: padding-box; }}

paned > separator {{ background: {mix(bg, fg, 0.10)}; min-width: 1px; min-height: 1px; }}
paned > separator:hover {{ background: {focus_ring}; }}

/* ---- find and the edit bar -------------------------------------------- */
.editorfind {{
    background: {menu_bg}; border: 1px solid {mix(menu_bg, fg, 0.18)};
    padding: 4px 8px;
}}
.editorfind entry, .prism entry {{
    background: {sunken}; color: {fg}; border: 1px solid {sunken};
    border-radius: 2px; padding: 3px 8px; font-size: {BODY}px;
}}
.prism entry:focus {{ border-color: {focus_ring}; }}
.findtoggle {{
    background: transparent; color: {fg}; border: 1px solid transparent;
    border-radius: 3px; padding: 0 6px; min-height: 22px; font-size: {SMALL}px;
}}
.findtoggle:hover {{ background: {rgba(fg, 0.12)}; }}
.findtoggle:checked {{ background: {rgba(accent, 0.45)}; color: {t.get("ACTIVE_FG", fg)}; }}
.findstatus {{ color: {mix(menu_bg, fg, 0.65)}; font-size: {SMALL}px; }}

.editbar {{
    background: {menu_bg}; border-bottom: 1px solid {mix(menu_bg, fg, 0.18)};
    padding: 5px 8px;
}}
.editbartag {{
    color: {t.get("ACTIVE_FG", fg)}; background: {accent}; font-size: {MICRO}px;
    font-weight: 700; letter-spacing: 1px; padding: 1px 7px; border-radius: 2px;
}}
.editbarnote {{ color: {mix(menu_bg, fg, 0.60)}; font-size: {SMALL}px; padding: 0 4px; }}
.editbargo {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 3px 12px; font-weight: 400;
}}
.editbargo:hover {{ background: {button_hover}; }}
.editbargo:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.iconbtn {{
    background: transparent; border: none; color: {mix(strip, fg, 0.80)};
    border-radius: 3px; padding: 0 4px; min-height: 22px; min-width: 22px;
}}
.iconbtn:hover {{ background: {rgba(fg, 0.12)}; color: {t.get("ACTIVE_FG", fg)}; }}

/* ---- the run controls ------------------------------------------------- */
.runbar {{ background: transparent; padding: 0 2px; }}
.runbtn-main {{
    background: transparent; color: {mix(strip, ok, 0.90)}; border: none;
    border-radius: 3px; padding: 0 8px; font-weight: 400; font-size: {SMALL}px;
    min-height: 22px;
}}
.runbtn-main:hover {{ background: {rgba(fg, 0.12)}; }}
.runbtn-main:disabled {{ background: transparent; color: {mix(strip, fg, 0.40)}; }}
.runbar combobox button {{
    background: transparent; color: {mix(strip, fg, 0.75)}; border: none;
    border-radius: 3px; padding: 0 6px; min-height: 22px; font-size: {SMALL}px;
}}
.runbar combobox button:hover {{ background: {rgba(fg, 0.12)}; color: {fg}; }}
.runsummary {{ color: {mix(strip, fg, 0.65)}; font-size: {SMALL}px; padding: 0 2px; }}
.runstate {{ color: {mix(strip, fg, 0.65)}; font-size: {SMALL}px; padding: 0 4px; }}
.runstate.live {{ color: {accent2}; }}
.runinstall {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 0 10px; font-size: {SMALL}px; min-height: 22px;
}}
.runinstall:hover {{ background: {button_hover}; }}
.runopen {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 0 10px; font-size: {SMALL}px; min-height: 22px;
}}
.runopen:hover {{ background: {button_hover}; }}

/* ---- bottom panel ----------------------------------------------------- */
.panelhead {{
    background: {bg}; border-top: 1px solid {mix(bg, fg, 0.10)};
    padding: 0 8px 0 20px; min-height: 35px;
}}
.paneltab {{
    background: transparent; border: none; color: {mix(bg, fg, 0.60)};
    padding: 2px 10px; border-bottom: 1px solid transparent; border-radius: 0;
    font-size: {SMALL}px; font-weight: 400; letter-spacing: 0.4px;
}}
.paneltab:hover {{ color: {fg}; }}
.paneltab:checked {{
    color: {t.get("ACTIVE_FG", fg)};
    border-bottom: 1px solid {t.get("ACTIVE_FG", fg)};
}}
.termpick {{ color: {mix(bg, fg, 0.65)}; font-size: {SMALL}px; }}
.termpick button {{
    background: transparent; border: none; color: {mix(bg, fg, 0.65)};
    padding: 0 4px; min-height: 20px; font-size: {SMALL}px;
}}
.termpick button:hover {{ color: {fg}; }}
.outputview, .outputview text {{ background: {bg}; color: {fg}; }}

/* ---- the assistant ---------------------------------------------------- */
.assistpane {{ background: {panel}; }}
window.prism .assistpane {{ background: {bg}; }}
.assisthead {{ background: {panel}; padding: 3px 4px 3px 14px; min-height: 30px; }}
.assistlabel {{
    color: {mix(panel, fg, 0.92)}; font-size: {SMALL}px; letter-spacing: 0.4px;
}}
.assisthint {{ color: {accent2}; font-size: {SMALL}px; }}
.claudefloat {{
    background: {panel}; border: 1px solid {mix(panel, fg, 0.22)};
    border-radius: 4px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.62), 0 2px 6px rgba(0, 0, 0, 0.4);
}}
.claudefloat .assistpane {{ background: {bg}; }}
.claudefloat .assisthead {{
    background: {panel}; border-bottom: 1px solid {mix(panel, fg, 0.14)};
}}

/* ---- status bar ------------------------------------------------------- */
/* The blue strip along the bottom, which is the single most recognisable
   thing about this shape of window. */
.statusbar {{
    background: {status_bg}; border-top: none;
    padding: 0 4px; min-height: 22px;
}}
.statusitem {{ color: {status_fg}; font-size: {SMALL}px; padding: 0 5px; }}
.statusbtn {{
    color: {status_fg}; font-size: {SMALL}px; padding: 0 6px; border: none;
    background: transparent; border-radius: 0; min-height: 22px;
}}
.statusbtn:hover {{ background: {rgba("#ffffff", 0.14)}; color: {status_fg}; }}
.statusbad {{ color: {status_fg}; font-size: {SMALL}px; }}
.statusgood {{ color: {status_fg}; font-size: {SMALL}px; }}

/* ---- source control ----------------------------------------------------- */
.gitbranch {{
    background: {sunken}; color: {fg}; border: 1px solid {sunken};
    border-radius: 2px; padding: 3px 9px; font-size: {SMALL}px;
}}
.gitbranch:hover {{ border-color: {focus_ring}; }}
.gitsync {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 3px 9px; font-size: {SMALL}px;
}}
.gitsync:hover {{ background: {button_hover}; }}
.gitsync:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.gitmessage, .gitmessage text {{
    background: {sunken}; color: {fg}; padding: 5px 8px; font-size: {BODY}px;
}}
.gitcommit {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 5px 12px; font-size: {BODY}px;
}}
.gitcommit:hover {{ background: {button_hover}; }}
.gitcommit:disabled {{ background: {mix(panel, fg, 0.12)}; color: {dim}; }}
.gitrow {{ padding: 1px 2px 1px 4px; border-radius: 0; }}
.gitrow:hover {{ background: {hover}; }}
.gitname {{ color: {fg}; font-size: {BODY}px; }}
.gitfolder {{ color: {mix(panel, fg, 0.55)}; font-size: {SMALL}px; }}
.gitmod {{ color: {t.get("SYN_FUNCTION", accent2)}; font-family: monospace; }}
.gitadd {{ color: {ok}; font-family: monospace; }}
.gitdel {{ color: {urgent}; font-family: monospace; }}
.gitnew {{ color: {ok}; font-family: monospace; }}
.gitconflict {{ color: {urgent}; font-family: monospace; }}

/* ---- the selection popup ----------------------------------------------- */
.selbar, .selbar > contents {{
    background: {menu_bg}; border: 1px solid {mix(menu_bg, fg, 0.20)};
    border-radius: 3px; padding: 0;
}}
.selbtn {{
    background: transparent; border: none; color: {fg};
    padding: 3px 10px; border-radius: 0; font-size: {BODY}px;
}}
.selbtn:hover {{ background: {menu_pick}; color: {t.get("ACTIVE_FG", fg)}; }}

/* ---- command palette --------------------------------------------------- */
/* Sits at the top of the window like the quick input it is copying. */
.palette {{
    background: {menu_bg}; border: 1px solid {mix(menu_bg, fg, 0.20)};
    border-radius: 4px;
}}
.palette entry {{
    background: {sunken}; color: {fg}; border: 1px solid {focus_ring};
    border-radius: 2px; padding: 4px 8px; font-size: {BODY}px;
}}
.palette scrolledwindow, .palette list, .palette viewport {{
    background: {menu_bg}; border: none;
}}
.palette list > row {{ background: transparent; }}
.palette list > row:hover {{ background: {hover}; }}
.palette list > row:selected {{ background: {picked}; box-shadow: none; }}
.palette list > row:selected label {{ color: {t.get("ACTIVE_FG", fg)}; }}
.paletterow {{ padding: 3px 10px; border-radius: 0; }}
.palettelabel {{ color: {fg}; font-size: {BODY}px; }}
.palettekeys {{ color: {mix(menu_bg, fg, 0.60)}; font-size: {SMALL}px; }}
.palettefrom {{ color: {mix(menu_bg, accent, 0.90)}; font-size: {MICRO}px; }}
.palettedetail {{ color: {mix(menu_bg, fg, 0.58)}; font-size: {SMALL}px; }}
.palette list > row:selected .palettedetail,
.palette list > row:selected .palettekeys {{ color: {mix(picked, fg, 0.75)}; }}
.palettehint {{ color: {mix(menu_bg, fg, 0.50)}; font-size: {SMALL}px; padding: 0 4px; }}

/* ---- search results ---------------------------------------------------- */
.searchhit {{ padding: 2px 10px; border-radius: 0; }}
.searchhit:hover {{ background: {hover}; }}
.searchfile {{ color: {fg}; font-size: {BODY}px; }}
.searchline {{ color: {mix(panel, fg, 0.50)}; font-family: monospace; font-size: {SMALL}px; }}
.searchtext {{ color: {mix(panel, fg, 0.80)}; font-family: monospace; font-size: {SMALL}px; }}
.searchcount {{ color: {mix(panel, fg, 0.55)}; font-size: {SMALL}px; }}

/* ---- extensions -------------------------------------------------------- */
.extrow {{
    background: transparent; border: none; border-bottom: 1px solid {mix(panel, fg, 0.10)};
    border-radius: 0; padding: 8px 12px; margin-bottom: 0;
}}
.extrow:hover {{ background: {hover}; }}
.extname {{ color: {fg}; font-weight: 600; font-size: {BODY}px; }}
.extblurb {{ color: {mix(panel, fg, 0.55)}; font-size: {SMALL}px; }}
.extbad {{ color: {urgent}; font-size: {SMALL}px; font-family: monospace; }}

/* ---- welcome ----------------------------------------------------------- */
.welcome {{ background: {bg}; }}
.welcomemark {{ color: {accent}; font-weight: 700; }}
.welcometitle {{ color: {mix(bg, fg, 0.90)}; }}
.welcomesub {{ color: {mix(bg, fg, 0.55)}; font-size: {BODY}px; }}
.welcomehead {{
    color: {mix(bg, fg, 0.80)}; font-size: {BODY}px; font-weight: 600;
    letter-spacing: 0;
}}
.welcomeaction {{
    background: transparent; border: none; color: {mix(bg, accent, 0.95)};
    padding: 2px 6px 2px 0; font-size: {BODY}px;
}}
.welcomeaction:hover {{ color: {t.get("ACTIVE_FG", fg)}; background: transparent; }}
.welcomerow {{ color: {mix(bg, fg, 0.50)}; font-size: {SMALL}px; }}
.welcomekey {{ color: {fg}; font-family: monospace; }}
.welcomeinvite {{ color: {accent}; font-size: {SMALL}px; }}

/* ---- preferences ------------------------------------------------------- */
.prefs {{ background: {panel}; color: {fg}; font-size: {BODY}px; }}
.prefs notebook {{ background: {panel}; }}
.prefs notebook header {{ background: {panel}; border-bottom: 1px solid {mix(panel, fg, 0.12)}; }}
.prefs notebook tab {{ padding: 5px 12px; color: {mix(panel, fg, 0.65)}; }}
.prefs notebook tab:checked {{
    color: {fg}; box-shadow: inset 0 -1px {t.get("ACTIVE_FG", fg)};
}}
.heading {{ color: {fg}; font-weight: 600; margin-top: 8px; }}
.hint {{ color: {mix(panel, fg, 0.55)}; font-size: {SMALL}px; }}
.prefs button {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; border: none;
    border-radius: 2px; padding: 4px 12px;
}}
.prefs button:hover {{ background: {button_hover}; }}
.prefs button:disabled {{ background: {mix(panel, fg, 0.12)}; color: {dim}; }}
.prefs entry {{
    background: {sunken}; color: {fg}; border: 1px solid {sunken};
    border-radius: 2px; padding: 4px 8px; caret-color: {fg};
}}
.prefs entry:focus {{ border-color: {focus_ring}; }}
.prefs entry selection {{ background: {picked}; color: {t.get("ACTIVE_FG", fg)}; }}
.prefs entry image {{ color: {mix(panel, fg, 0.55)}; }}
.prefs combobox button {{ background: {sunken}; color: {fg}; }}
.prefs checkbutton {{ color: {fg}; }}
.prefs scrolledwindow, .prefs viewport, .prefs list {{ background: {panel}; }}
.prefs headerbar, .prefs .titlebar {{
    background: {head}; color: {fg}; border-bottom: none;
}}

/* ---- github ------------------------------------------------------------ */
.ghbar {{
    background: {panel}; border: 1px solid {mix(panel, fg, 0.14)};
    border-radius: 3px; padding: 10px 12px;
}}
.ghlist {{ background: {sunken}; }}
.ghlist row {{ border-bottom: 1px solid {mix(panel, fg, 0.10)}; }}
.ghlist row:selected {{ background: {picked}; }}
.ghname {{ color: {fg}; font-weight: 600; }}
.ghtag {{
    background: {skin("BADGE_BG", raised)}; color: {fg}; font-size: {MICRO}px;
    border-radius: 10px; padding: 0 7px;
}}
.ghkey {{ color: {mix(panel, fg, 0.55)}; font-family: monospace; font-size: {SMALL}px; }}
.devicecode {{
    color: {accent2}; font-family: monospace; font-size: 30px;
    font-weight: 700; letter-spacing: 3px;
}}

/* ---- the update card --------------------------------------------------- */
.whatsnew {{ background: {panel}; }}
.wnhead {{ background: {panel}; border-bottom: 1px solid {mix(panel, fg, 0.12)}; }}
.wntitle {{ color: {fg}; font-size: 17px; font-weight: 600; }}
.wnsub {{ color: {mix(panel, fg, 0.55)}; font-size: {SMALL}px; }}
.wnflag {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)}; font-size: {SMALL}px;
    font-weight: 400; padding: 4px 20px;
}}
.wnnotes {{ background: {panel}; }}
.wnbullet {{ color: {accent}; }}
.wnnote {{ color: {fg}; font-size: {BODY}px; }}
.wnactions {{
    background: {panel}; border-top: 1px solid {mix(panel, fg, 0.12)};
    padding: 12px 16px;
}}
.whatsnew button.wnbtn {{
    background: {skin("BADGE_BG", raised)}; color: {fg}; border: none;
    border-radius: 2px; padding: 5px 14px; font-size: {BODY}px;
}}
.whatsnew button.wnbtn:hover {{ background: {mix(skin("BADGE_BG", raised), fg, 0.12)}; }}
.whatsnew button.wnprimary {{
    background: {button_bg}; color: {t.get("ACTIVE_FG", fg)};
}}
.whatsnew button.wnprimary:disabled {{
    background: {mix(panel, fg, 0.12)}; color: {dim};
}}
.whatsnew button.wnprimary:hover {{ background: {button_hover}; }}
.wncmd {{
    background: {sunken}; color: {mix(panel, fg, 0.70)}; font-family: monospace;
    font-size: {SMALL}px; padding: 8px 20px; border-top: 1px solid {mix(panel, fg, 0.12)};
}}
"""
