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

    # every piece of chrome sits on this one colour
    head = panel
    bar = panel
    raised = mix(panel, fg, 0.09) if not light else mix(panel, "#000000", 0.07)
    sunken = mix(bg, "#000000", 0.25) if not light else mix(bg, "#000000", 0.05)
    # a hairline inside the chrome: present, but never the loudest thing in view
    line = mix(panel, fg, 0.13) if not light else mix(panel, "#000000", 0.13)
    ui_font = cfg.get("UI_FONT", "")
    font_rule = "font-family: %s;" % ui_font if ui_font else ""

    return f"""
* {{ outline: none; }}

/* Everything that answers to the pointer fades rather than snaps. It is a
   tenth of a second and it is most of the difference between an application
   that feels built and one that feels assembled. */
button, .toolbtn, .iconbtn, .edtab, .activitybtn, .paneltab, .statusbtn,
.sidebtn, menuitem, .palette list > row {{
    transition: background-color 120ms ease-out, color 120ms ease-out,
                border-color 120ms ease-out, opacity 120ms ease-out;
}}

window.prism, .prism {{
    background: {bg}; color: {fg}; {font_rule} font-size: {BODY}px;
}}

/* ---- title bar ------------------------------------------------------- */
headerbar.prismhead, .prismhead {{
    background: {head}; border-bottom: 1px solid {line};
    padding: 0 4px; min-height: 32px;
}}
/* One line, not two: the file in the foreground colour, where it came from
   trailing off in the dim one. A stacked subtitle costs ten pixels of height
   on every window for a path most people already know. */
.prismtitle {{ color: {fg}; font-weight: 600; font-size: {BODY}px; }}
.prismsubtitle {{ color: {dim}; font-size: {SMALL}px; }}
.prismhead button, .toolbtn {{
    background: transparent; border: none; color: {dim};
    border-radius: 5px; padding: 1px 7px; min-height: 24px; min-width: 24px;
}}
.prismhead button:hover, .toolbtn:hover {{ background: {raised}; color: {fg}; }}
.appmenu {{ padding: 1px 6px; }}
.appmenu:active, .appmenu:checked {{ background: {raised}; color: {fg}; }}
.toolbtn:checked, .toolbtn.on {{ background: {rgba(accent, 0.20)}; color: {accent}; }}

menubar, .prismmenu {{ background: transparent; color: {fg}; }}
menubar > menuitem {{
    padding: 3px 8px; color: {dim}; border-radius: 5px; font-size: {BODY}px;
}}
menubar > menuitem:hover, menubar > menuitem:selected {{
    background: {raised}; color: {fg};
}}
/* Menus and popovers are their own toplevels, so nothing cascades into them
   from .prism — they need the font size saying again. */
menu, .prismmenu menu, popover, popover.background {{
    background: {panel}; border: 1px solid {border}; border-radius: 8px;
    color: {fg}; padding: 4px; font-size: {BODY}px;
}}
menu menuitem, popover modelbutton {{
    padding: 4px 11px; border-radius: 5px; color: {fg};
}}
menu menuitem:hover, popover modelbutton:hover {{ background: {accent}; color: {on_accent}; }}
menu separator {{ background: {line}; margin: 4px 2px; }}
menu menuitem:disabled, menu menuitem label:disabled {{ color: {mix(panel, fg, 0.35)}; }}
menu accelerator {{ color: {dim}; }}

/* ---- activity bar ---------------------------------------------------- */
/* Same colour as the side bar it introduces, so the two read as one column
   and the only edge in that corner of the window is the one against the code.
   The current one is marked by a hairline and a brighter icon rather than by a
   filled block: five stacked blocks is what makes a rail look like a wall. */
.activitybar {{ background: {bar}; padding: 3px 0; }}
.activitybtn {{
    background: transparent; border: none; color: {mix(bar, fg, 0.42)};
    min-width: 40px; min-height: 34px; padding: 0; border-radius: 0;
    border-left: 2px solid transparent;
}}
.activitybtn:hover {{ color: {fg}; background: transparent; }}
.activitybtn:checked {{
    color: {accent}; border-left: 2px solid {accent}; background: transparent;
}}
.activitybtn:checked:hover {{ color: {accent}; }}

/* ---- side bar -------------------------------------------------------- */
.sidebar {{ background: {panel}; }}
.sidehead {{ padding: 6px 8px 4px 12px; background: {panel}; }}
.sidetitle {{
    color: {dim}; font-size: {MICRO}px; font-weight: 700; letter-spacing: 1.2px;
}}
.sidebar treeview, .sidebar textview, .sidebar list {{
    background: {panel}; color: {fg};
}}
.sidebar treeview {{ font-size: {BODY}px; }}
.sidebar treeview:selected, .sidebar list > row:selected {{
    background: {rgba(accent, 0.22)}; color: {fg};
}}
.sidebar treeview:hover {{ background: {rgba(fg, 0.05)}; }}
.sidebar scrollbar {{ background: transparent; }}
.sideempty {{ color: {dim}; font-size: {SMALL}px; }}
.sidebtn {{
    background: {raised}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 5px 11px; font-size: {BODY}px;
}}
.sidebtn:hover {{ background: {mix(raised, fg, 0.10)}; border-color: {accent}; }}
.recentlink {{
    background: transparent; border: none; color: {accent};
    padding: 1px 4px; font-size: {SMALL}px;
}}
.recentlink:hover {{ color: {fg}; }}

/* ---- editor tabs ----------------------------------------------------- */
/* The active tab is the editor's own colour and has no line under it, so the
   tab and the file below it are one shape. The others stay chrome-coloured. */
.edtabs {{ background: {head}; }}
.editorhead {{ background: {head}; padding: 0 4px 0 0; }}
.edtab {{
    background: transparent; border-top: 2px solid transparent;
    padding: 2px 4px 2px 10px; color: {dim}; min-height: 24px;
}}
.edtab:hover {{ background: {rgba(fg, 0.05)}; color: {fg}; }}
.edtab.active {{
    background: {bg}; color: {fg}; border-top: 2px solid {accent};
}}
.edtab label {{ color: inherit; font-size: {BODY}px; }}
/* Present on every tab, but only asking to be noticed on the one you are on. */
.edtabclose {{
    color: {dim}; background: transparent; border: none; opacity: 0.35;
    min-width: 16px; min-height: 16px; padding: 0; border-radius: 8px;
}}
.edtab.active .edtabclose, .edtab:hover .edtabclose {{ opacity: 1; }}
.edtabclose:hover {{ background: {rgba(urgent, 0.22)}; color: {urgent}; opacity: 1; }}

/* ---- the editor itself ------------------------------------------------ */
.codeeditor, .codeeditor text {{ background: {bg}; color: {fg}; }}
.codeeditor border {{ background: {bg}; color: {mix(bg, fg, 0.30)}; }}
scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{
    background: {mix(bg, fg, 0.20)}; border-radius: 4px; min-width: 7px; min-height: 7px;
    border: 2px solid transparent; background-clip: padding-box;
}}
scrollbar slider:hover {{ background: {mix(bg, fg, 0.36)}; background-clip: padding-box; }}

/* A hairline, not a handle. Four pixels of grey between every pane is a
   surprising amount of the window once you count it up. */
paned > separator {{
    background: {line}; min-width: 1px; min-height: 1px;
}}
paned > separator:hover {{ background: {accent}; }}

/* ---- find and the edit bar -------------------------------------------- */
.editorfind {{ background: {head}; border-bottom: 1px solid {line}; padding: 4px 8px; }}
.editorfind entry, .prism entry {{
    background: {sunken}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 2px 9px; font-size: {BODY}px;
}}
.prism entry:focus {{ border-color: {accent}; }}
.findtoggle {{
    background: transparent; color: {dim}; border: 1px solid {line};
    border-radius: 6px; padding: 0 8px; min-height: 22px; font-size: {SMALL}px;
}}
.findtoggle:checked {{ background: {accent}; color: {on_accent}; }}
.findstatus {{ color: {dim}; font-size: {SMALL}px; }}

.editbar {{
    background: {mix(head, accent, 0.10)}; border-bottom: 1px solid {rgba(accent, 0.55)};
    padding: 5px 8px;
}}
.editbartag {{
    color: {on_accent}; background: {accent}; font-size: {MICRO}px; font-weight: 700;
    letter-spacing: 1px; padding: 1px 7px; border-radius: 4px;
}}
.editbarnote {{ color: {dim}; font-size: {SMALL}px; padding: 0 4px; }}
.editbargo {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 6px; padding: 2px 12px; font-weight: 600;
}}
.editbargo:hover {{ background: {mix(accent, fg, 0.18)}; }}
.editbargo:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.iconbtn {{
    background: transparent; border: none; color: {dim};
    border-radius: 5px; padding: 0 4px; min-height: 20px; min-width: 20px;
}}
.iconbtn:hover {{ background: {raised}; color: {fg}; }}

/* ---- the run controls ------------------------------------------------- */
/* These live at the right hand end of the tab strip now, so this is a group of
   controls rather than a bar: no background, no border, no row of its own. */
.runbar {{ background: transparent; padding: 0 2px; }}
.runbtn-main {{
    background: {rgba(ok, 0.16)}; color: {ok}; border: 1px solid {rgba(ok, 0.45)};
    border-radius: 5px; padding: 0 10px; font-weight: 600; font-size: {SMALL}px;
    min-height: 20px;
}}
.runbtn-main:hover {{ background: {ok}; color: {readable_on(ok)}; border-color: {ok}; }}
.runbtn-main:disabled {{
    background: transparent; color: {dim}; border-color: {line};
}}
.runbar combobox button {{
    background: transparent; color: {dim}; border: 1px solid {line};
    border-radius: 5px; padding: 0 6px; min-height: 20px; font-size: {SMALL}px;
}}
.runbar combobox button:hover {{ color: {fg}; border-color: {accent}; }}
.runsummary {{ color: {dim}; font-size: {SMALL}px; padding: 0 2px; }}
.runstate {{ color: {dim}; font-size: {SMALL}px; padding: 0 4px; }}
.runstate.live {{ color: {accent}; }}
.runinstall {{
    background: {accent2}; color: {readable_on(accent2)}; border: none;
    border-radius: 5px; padding: 0 10px; font-weight: 600; font-size: {SMALL}px;
    min-height: 20px;
}}
.runinstall:hover {{ background: {mix(accent2, fg, 0.18)}; }}
.runopen {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 5px; padding: 0 10px; font-weight: 600; font-size: {SMALL}px;
    min-height: 20px;
}}
.runopen:hover {{ background: {mix(accent, fg, 0.18)}; }}

/* ---- bottom panel ----------------------------------------------------- */
.panelhead {{
    background: {head}; border-top: 1px solid {line};
    padding: 0 4px 0 8px; min-height: 28px;
}}
.paneltab {{
    background: transparent; border: none; color: {dim};
    padding: 3px 9px; border-bottom: 2px solid transparent; border-radius: 0;
    font-size: {MICRO}px; font-weight: 700; letter-spacing: 0.8px;
}}
.paneltab:hover {{ color: {fg}; }}
.paneltab:checked {{ color: {fg}; border-bottom: 2px solid {accent}; }}
.termpick {{ color: {dim}; font-size: {SMALL}px; }}
.termpick button {{
    background: transparent; border: none; color: {dim}; padding: 0 4px;
    min-height: 20px; font-size: {SMALL}px;
}}
.termpick button:hover {{ color: {fg}; }}
.outputview, .outputview text {{ background: {bg}; color: {fg}; }}

/* ---- the assistant ---------------------------------------------------- */
.assistpane {{ background: {panel}; }}
/* Claude in its own window has no editor beside it to borrow an edge from,
   and where there is no window manager GTK draws its own title bar, which
   arrives Adwaita-white unless it is told otherwise. */
window.prism .assistpane {{ background: {bg}; }}
/* Floating over the editor: it has to read as a thing hovering above the
   code, so it gets the panel colour, a real border and a shadow, and the
   session inside keeps the editor's own background. */
.claudefloat {{
    background: {panel}; border: 1px solid {mix(panel, fg, 0.22)};
    border-radius: 10px;
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.4);
}}
.claudefloat .assistpane {{
    background: {bg}; border-radius: 0 0 9px 9px;
}}
.claudefloat .assisthead {{
    background: {panel}; border-radius: 9px 9px 0 0;
    border-bottom: 1px solid {line}; padding: 4px 6px 4px 12px;
}}

window.prism > headerbar, window.prism > .titlebar {{
    background: {head}; color: {fg}; border-bottom: 1px solid {line};
    min-height: 30px;
}}
window.prism > headerbar .title, window.prism > .titlebar .title {{
    color: {fg}; font-size: {BODY}px; font-weight: 600;
}}
.assisthead {{ background: {head}; padding: 2px 4px 2px 12px; min-height: 28px; }}
.assistlabel {{
    color: {dim}; font-size: {MICRO}px; font-weight: 700; letter-spacing: 1.2px;
}}
.assisthint {{ color: {accent}; font-size: {SMALL}px; }}

/* ---- status bar ------------------------------------------------------- */
/* Chrome-coloured like everything else. The old accent wash made the bottom of
   every window a coloured band competing with the code above it. */
.statusbar {{
    background: {head}; border-top: 1px solid {line};
    padding: 1px 8px; min-height: 20px;
}}
.statusitem {{ color: {mix(panel, fg, 0.62)}; font-size: {SMALL}px; }}
.statusbtn {{
    color: {mix(panel, fg, 0.62)}; font-size: {SMALL}px; padding: 0 6px; border: none;
    background: transparent; border-radius: 4px; min-height: 17px;
}}
.statusbtn:hover {{ background: {rgba(fg, 0.12)}; color: {fg}; }}
.statusbad {{ color: {urgent}; font-size: {SMALL}px; }}
.statusgood {{ color: {ok}; font-size: {SMALL}px; }}

/* ---- source control ----------------------------------------------------- */
.gitbranch {{
    background: {raised}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 2px 9px; font-size: {SMALL}px;
}}
.gitbranch:hover {{ border-color: {accent}; }}
.gitsync {{
    background: {accent}; color: {on_accent}; border: none;
    border-radius: 6px; padding: 2px 9px; font-size: {SMALL}px; font-weight: 600;
}}
.gitsync:hover {{ background: {mix(accent, fg, 0.18)}; }}
.gitsync:disabled {{ background: {mix(panel, fg, 0.14)}; color: {dim}; }}
.gitmessage, .gitmessage text {{
    background: {sunken}; color: {fg}; padding: 5px 8px; font-size: {BODY}px;
}}
.gitcommit {{
    background: {ok}; color: {readable_on(ok)}; border: none;
    border-radius: 6px; padding: 4px 12px; font-weight: 700; font-size: {BODY}px;
}}
.gitcommit:hover {{ background: {mix(ok, fg, 0.18)}; }}
.gitcommit:disabled {{ background: {mix(panel, fg, 0.12)}; color: {dim}; }}
.gitrow {{ padding: 1px 2px 1px 4px; border-radius: 4px; }}
.gitrow:hover {{ background: {mix(panel, fg, 0.09)}; }}
.gitname {{ color: {fg}; font-size: {BODY}px; }}
.gitfolder {{ color: {dim}; font-size: {SMALL}px; }}
.gitmod {{ color: {accent2}; font-weight: 700; font-family: monospace; }}
.gitadd {{ color: {ok}; font-weight: 700; font-family: monospace; }}
.gitdel {{ color: {urgent}; font-weight: 700; font-family: monospace; }}
.gitnew {{ color: {ok}; font-weight: 700; font-family: monospace; }}
.gitconflict {{ color: {urgent}; font-weight: 700; font-family: monospace; }}

/* ---- the selection popup ----------------------------------------------- */
.selbar, .selbar > contents {{
    background: {raised}; border: 1px solid {border}; border-radius: 8px;
    padding: 0;
}}
.selbtn {{
    background: transparent; border: none; color: {fg};
    padding: 3px 10px; border-radius: 6px; font-size: {SMALL}px;
}}
.selbtn:hover {{ background: {accent}; color: {on_accent}; }}

/* ---- command palette --------------------------------------------------- */
.palette {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
.palette entry {{
    background: {sunken}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 5px 10px; font-size: {BODY}px;
}}
.palette entry:focus {{ border-color: {accent}; }}
.palette scrolledwindow, .palette list, .palette viewport {{
    background: {panel}; border: none;
}}
.palette list > row {{ background: transparent; }}
.palette list > row:hover {{ background: {mix(panel, fg, 0.08)}; }}
/* A tinted row with a mark down its edge, not a solid bar of accent: the
   palette is on screen while you read the list, and a neon stripe is hard to
   read past. */
.palette list > row:selected {{
    background: {rgba(accent, 0.20)}; box-shadow: inset 2px 0 {accent};
}}
.palette list > row:selected label {{ color: {fg}; }}
.paletterow {{ padding: 3px 10px; border-radius: 5px; }}
.palettelabel {{ color: {fg}; font-size: {BODY}px; }}
.palettekeys {{ color: {dim}; font-size: {SMALL}px; font-family: monospace; }}
.palettefrom {{ color: {accent}; font-size: {MICRO}px; letter-spacing: 0.6px; }}
.palettedetail {{ color: {dim}; font-size: {SMALL}px; }}
.palette list > row:selected .palettedetail,
.palette list > row:selected .palettekeys {{ color: {mix(panel, fg, 0.65)}; }}
.palettehint {{ color: {mix(panel, fg, 0.42)}; font-size: {MICRO}px; padding: 0 4px; }}

/* ---- search results ---------------------------------------------------- */
.searchhit {{ padding: 2px 10px; border-radius: 4px; }}
.searchfile {{ color: {accent}; font-size: {SMALL}px; font-weight: 600; }}
.searchline {{ color: {dim}; font-family: monospace; font-size: {SMALL}px; }}
.searchtext {{ color: {fg}; font-family: monospace; font-size: {SMALL}px; }}
.searchcount {{ color: {dim}; font-size: {SMALL}px; }}

/* ---- extensions -------------------------------------------------------- */
.extrow {{
    background: {mix(panel, fg, 0.05)}; border: 1px solid {line};
    border-radius: 7px; padding: 8px 11px; margin-bottom: 5px;
}}
.extname {{ color: {fg}; font-weight: 600; font-size: {BODY}px; }}
.extblurb {{ color: {dim}; font-size: {SMALL}px; }}
.extbad {{ color: {urgent}; font-size: {SMALL}px; font-family: monospace; }}

/* ---- welcome ----------------------------------------------------------- */
.welcome {{ background: {bg}; }}
.welcomemark {{ color: {accent}; font-weight: 700; }}
.welcometitle {{ color: {fg}; }}
.welcomesub {{ color: {dim}; font-size: {BODY}px; }}
.welcomehead {{
    color: {mix(bg, fg, 0.45)}; font-size: {MICRO}px; font-weight: 700;
    letter-spacing: 1.4px;
}}
.welcomeaction {{
    background: transparent; border: none; color: {accent};
    padding: 2px 6px 2px 0; font-size: {BODY}px;
}}
.welcomeaction:hover {{ color: {fg}; background: transparent; }}
.welcomerow {{ color: {mix(bg, fg, 0.42)}; font-size: {SMALL}px; }}
.welcomekey {{ color: {fg}; font-family: monospace; }}
.welcomeinvite {{ color: {accent}; font-size: {SMALL}px; }}

/* ---- preferences ------------------------------------------------------- */
.prefs {{ background: {bg}; color: {fg}; font-size: {BODY}px; }}
.prefs notebook {{ background: {bg}; }}
.prefs notebook header {{ background: {head}; border-bottom: 1px solid {line}; }}
.prefs notebook tab {{ padding: 5px 12px; color: {dim}; }}
.prefs notebook tab:checked {{ color: {fg}; box-shadow: inset 0 -2px {accent}; }}
.heading {{ color: {fg}; font-weight: 700; margin-top: 8px; }}
.hint {{ color: {dim}; font-size: {SMALL}px; }}
.prefs button {{
    background: {raised}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 3px 10px;
}}
.prefs button:hover {{ border-color: {accent}; }}
.prefs button:disabled {{ color: {dim}; border-color: {line}; }}
/* Without these, every text box in every dialog arrives Adwaita-white. */
.prefs entry {{
    background: {sunken}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 4px 8px; caret-color: {fg};
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
    background: {head}; color: {fg}; border-bottom: 1px solid {line};
}}

/* ---- github ------------------------------------------------------------ */
.ghbar {{
    background: {head}; border: 1px solid {line}; border-radius: 8px;
    padding: 10px 12px;
}}
.ghlist {{ background: {sunken}; }}
.ghlist row {{ border-bottom: 1px solid {line}; }}
.ghlist row:selected {{ background: {raised}; }}
.ghname {{ color: {fg}; font-weight: 700; }}
.ghtag {{
    background: {raised}; color: {dim}; font-size: {MICRO}px; border-radius: 4px;
    padding: 0 6px;
}}
.ghkey {{ color: {dim}; font-family: monospace; font-size: {SMALL}px; }}
.devicecode {{
    color: {accent}; font-family: monospace; font-size: 30px;
    font-weight: 700; letter-spacing: 3px;
}}

/* ---- the update card --------------------------------------------------- */
.whatsnew {{ background: {bg}; }}
.wnhead {{ background: {head}; border-bottom: 1px solid {line}; }}
.wntitle {{ color: {fg}; font-size: 17px; font-weight: 700; }}
.wnsub {{ color: {dim}; font-size: {SMALL}px; }}
.wnflag {{
    background: {accent2}; color: {on_accent2}; font-size: {SMALL}px;
    font-weight: 700;
    padding: 4px 20px;
}}
.wnnotes {{ background: {bg}; }}
.wnbullet {{ color: {accent}; }}
.wnnote {{ color: {fg}; font-size: {BODY}px; }}
/* `.prefs button` is class+element, so a bare `.wnbtn` loses to it. These
   selectors have to outrank it or the buttons stay the preferences grey. */
.wnactions {{
    background: {head}; border-top: 1px solid {line}; padding: 12px 16px;
}}
.whatsnew button.wnbtn {{
    background: {raised}; color: {fg}; border: 1px solid {line};
    border-radius: 6px; padding: 5px 14px; font-size: {BODY}px;
}}
.whatsnew button.wnbtn:hover {{ border-color: {accent}; background: {panel}; }}
.whatsnew button.wnprimary {{
    background: {accent}; color: {on_accent}; border-color: {accent};
    font-weight: 700;
}}
.whatsnew button.wnprimary:disabled {{
    background: {raised}; color: {dim}; border-color: {line};
}}
.whatsnew button.wnprimary:hover {{
    background: {accent}; border-color: {fg}; color: {on_accent};
}}
.wncmd {{
    background: {raised}; color: {dim}; font-family: monospace; font-size: {SMALL}px;
    padding: 8px 20px; border-top: 1px solid {line};
}}
"""
