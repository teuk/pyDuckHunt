"""Shared DH051 visual refinement for the standalone ranking page."""

DH051_REFINEMENT_STYLE = r"""
/* DH051 — quiet technical editorial refinement */
:root{--background:#0a1012;--foreground:#e8edec;--card:#101719;--card-2:#141d1f;--line:#263235;--text-soft:#a8b3b1;--amber:#d7a84c;--amber-soft:#e4c37c;--cyan:#79bdb6;--cyan-dark:#172b2d}
body{background:#0a1012;font-size:15px;line-height:1.6}
.site-noise{display:none}
.site-container{width:min(100% - 48px,1120px)}
.site-header{background:#0a1012f5;border-bottom-color:var(--line);backdrop-filter:blur(10px)}
.header-inner{height:64px;gap:26px}
.brand{gap:10px}
.brand-mark{color:var(--amber);font-size:21px}
.brand-copy{color:#8d9a98;font-size:9px;letter-spacing:.07em}
.primary-nav{gap:2px}
.primary-nav a{padding:8px 11px;border-radius:5px;color:#b5bfbd;font:600 12px/1.2 "Avenir Next",Avenir,"Segoe UI",sans-serif;text-transform:none;letter-spacing:0}
.primary-nav a:hover{color:#fff;background:#151e20}
.header-status{color:#8dc4be;font-size:10px;letter-spacing:.04em}
.header-status i,.eyebrow span{box-shadow:none}
.duckhunt-subnav{top:64px;background:#0f1618f7;border-bottom-color:var(--line);backdrop-filter:blur(8px)}
.duckhunt-subnav-inner{min-height:46px}
.duckhunt-subbrand{color:var(--amber-soft);font-size:11px;text-transform:none;letter-spacing:.02em}
.target-mark{font-size:17px}
.duckhunt-subnav nav{gap:0}
.duckhunt-subnav nav a{padding:14px 10px 12px;border-bottom:2px solid transparent;color:#9eaaa8;font:12px/1 "Avenir Next",Avenir,"Segoe UI",sans-serif;text-transform:none;letter-spacing:0}
.duckhunt-subnav nav a:hover,.duckhunt-subnav nav a[aria-current=page]{color:#eef2f1;border-bottom-color:var(--amber);background:transparent}
.ranking-hero{background:#0b1214;border-bottom-color:var(--line)}
.hero-grid{min-height:230px;grid-template-columns:minmax(0,1fr) 160px;gap:46px;padding-block:38px 30px}
.eyebrow{color:#8dc4be;font-size:9px;letter-spacing:.1em}
.hero-grid h1{margin:13px 0 12px;font-size:clamp(31px,3.8vw,43px);line-height:1.09;letter-spacing:-.035em}
.hero-grid h1 em{color:var(--amber-soft)}
.hero-grid p{max-width:700px;color:#b3bfbd;font-size:14px;line-height:1.7}
.hero-signal{height:124px;border-color:#354346;border-radius:8px;background:#101719;box-shadow:none}
.hero-signal:after{display:none}
.hero-signal span{top:17px;color:#82908e}
.hero-signal b{color:var(--amber-soft);font-size:34px}
.hero-signal i{bottom:17px;color:#91c6c0}
.summary-grid{margin-top:8px;border-color:var(--line);border-radius:7px}
.summary-grid article{min-height:76px;padding:15px 19px;background:#101719;border-color:var(--line)}
.summary-grid span{color:#8b9896;font-size:8px;letter-spacing:.08em}
.summary-grid strong{margin-top:8px;font-size:18px}
.ranking-section{padding-block:52px 66px}
.section-heading,.table-heading{gap:28px}
.section-heading>div>span,.table-heading>div>span{color:var(--amber-soft);letter-spacing:.1em}
.section-heading h2,.table-heading h2{margin-top:7px;font-size:26px;letter-spacing:-.025em}
.section-heading p{max-width:410px;color:#aab5b3;font-size:13px;line-height:1.6}
.podium-grid{gap:8px;margin-top:22px}
.podium-card{min-height:172px;padding:20px;border-color:var(--line);border-radius:7px;background:#101719}
.podium-card:after{display:none}
.podium-card.place-1{border-color:#655531;background:#141713}
.podium-name{margin-top:27px;font-size:21px}
.podium-score{margin-top:8px}
.podium-score strong{color:#9acbc5;font-size:24px}
.podium-score span{color:#899694}
.podium-meta{gap:5px;margin-top:18px}
.podium-meta span{padding:5px 7px;border-color:#344246;color:#a5b0ae;font-size:8px}
.empty-state,.table-empty{margin-top:22px;padding:32px;border-color:#46575a;border-radius:7px;background:#101719}
.table-heading{margin-top:50px;padding-bottom:15px}
.table-heading time{color:#879492;font-size:8px}
.ranking-table-shell{margin-top:12px;border-color:var(--line);border-radius:7px;background:#0d1416;box-shadow:none}
th{padding:13px 11px;background:#141d1f;color:#9aa7a5;font-size:8px;letter-spacing:.07em}
td{padding:12px 11px;border-bottom-color:#202c2f;color:#c7cfcd;font-size:11px}
tbody tr:nth-child(even){background:#11191b}
tbody tr:hover{background:#151f21}
.rank-badge{width:25px;height:25px;border-color:#46575a;border-radius:5px;color:#a0abaa}
.rank-1 .rank-badge{border-color:var(--amber);color:var(--amber-soft);box-shadow:none}
.rank-2 .rank-badge,.rank-3 .rank-badge{border-color:#597874;color:#9bcac5}
.hunter{font-size:12px}
.ranking-note{color:#879492;font-size:9px;letter-spacing:.02em}
.site-footer{background:#080d0f;border-top-color:var(--line)}
.footer-inner{min-height:66px;color:#7e8b89;font-size:8px}
@media(max-width:980px){.hero-grid{grid-template-columns:1fr}.hero-signal{display:none}.podium-card{min-height:150px}}
@media(max-width:700px){.site-container{width:min(100% - 28px,1120px)}.header-inner{height:60px}.brand-copy{display:none}.duckhunt-subnav{top:60px}.duckhunt-subnav-inner{gap:4px;padding-block:7px 3px}.duckhunt-subnav nav a{padding:10px 9px 9px;font-size:11px}.hero-grid{padding-block:31px 26px}.hero-grid h1{font-size:29px;line-height:1.12}.summary-grid{margin-top:6px}.summary-grid article{min-height:70px;padding:14px}.ranking-section{padding-block:42px 54px}.section-heading p{font-size:12px;text-align:left}.table-heading{margin-top:40px}.ranking-table-shell tr{padding:14px;border-color:var(--line);border-radius:7px;background:#101719}.ranking-table-shell td{font-size:11px}.ranking-table-shell td:before{color:#879492;font-size:8px}}
"""
