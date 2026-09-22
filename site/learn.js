// Glossary + tooltips. Any element with data-t="<key>" gets a tooltip; the glossary section renders from GLOSSARY.
// Edit definitions here. Keep them short, sourced from FEC rules, and nonpartisan.
window.GLOSSARY = {
  // ---- the vehicles
  candidate_committee: {t: "Candidate committee", d: "The campaign's own account (its \"principal campaign committee\"). In 2025-26 an individual can give up to $3,500 per election, so $7,000 across a primary and a general; a multicandidate PAC can give $5,000 per election. It controls its own ads and message, and reports quarterly plus before and after each election."},
  party_committee: {t: "Party committee", d: "National, congressional and state party organizations: DNC and RNC, DCCC and NRCC (House), DSCC and NRSC (Senate), plus state and local parties. They raise under limits, give directly to candidates, run independent expenditures, and can spend in coordination with candidates. The FEC codes them as committee type X or Y, which is how this page identifies them."},
  super_pac: {t: "Super PAC", d: "An \"independent expenditure-only\" committee. Since Citizens United v. FEC and SpeechNow.org v. FEC (both 2010), it can raise unlimited sums from individuals, corporations and unions, but it can't give to candidates or coordinate with them. Its donors are disclosed on its regular reports, which can lag its spending by weeks. This page also counts hybrid PACs (below) and single-candidate committees here (FEC types O, U, V, W)."},
  hybrid_pac: {t: "Hybrid PAC", d: "A PAC with two bank accounts: a limited one for giving to candidates and an unlimited one for independent expenditures. Allowed since Carey v. FEC (2011). Counted with super PACs on this page."},
  traditional_pac: {t: "Traditional PAC", d: "A political action committee, either connected to a corporation, union or trade group, or unconnected. It raises under limits ($5,000 a year per individual) and can give candidates up to $5,000 per election. Counted as \"other\" outside money on this page when it runs independent expenditures."},
  nonprofit: {t: "501(c) groups (\"dark money\")", d: "Social-welfare nonprofits (501(c)(4)), trade associations (501(c)(6)) and similar groups can run independent expenditures. They must report the spending, but generally don't disclose their donors unless the money was given for that ad. They appear on this page as \"other\" outside money."},
  outside_money: {t: "Outside money", d: "Spending on a race by anyone other than the candidates' own campaigns: super PACs, traditional PACs, nonprofits and party committees. On this page, \"party\" is split out and \"outside\" means everything that isn't a party committee."},
  conduit: {t: "Conduits (ActBlue, WinRed)", d: "Platforms that pass small-dollar contributions to candidates and committees. The money counts as coming from the individual donor, under the same limits, and shows up in the candidate's receipts."},

  // ---- the ways money is spent
  independent_expenditure: {t: "Independent expenditure (IE)", d: "Spending on an ad, mailer, text or canvass that explicitly calls for electing or defeating a candidate, made without coordinating with the candidate or a party. It has no dollar limit. It's reported on Schedule E, and near an election within 24 or 48 hours. This is most of the \"outside money\" on this page."},
  coordinated: {t: "Coordinated party spending", d: "Money a party spends on a candidate's behalf in cooperation with the campaign, such as ads made together or shared polling. It's reported on Schedule F, only on the party's regular reports. The Supreme Court's June 2026 ruling in NRSC v. FEC removed the limits on it, so parties can move money here from independent expenditures."},
  nrsc: {t: "NRSC v. FEC (2026)", d: "The Supreme Court decision (June 30, 2026) striking down limits on party coordinated spending. Parties can now spend without limit in cooperation with their candidates. That money is disclosed more slowly than independent expenditures, which is the blind spot flagged at the top of this page."},
  lowest_unit_charge: {t: "Lowest unit charge", d: "Federal law requires broadcast stations to sell candidates airtime at their lowest rate for comparable spots in the 45 days before a primary and the 60 days before a general. Super PACs and other outside groups pay market rates, which climb as Election Day nears. So a dollar raised by a candidate often buys more TV than a dollar spent by an outside group."},
  support_oppose: {t: "Support / oppose", d: "Every independent expenditure is reported as supporting or opposing one named candidate. This page converts that into the party it helps: supporting a Democrat or opposing a Republican helps Democrats, and the reverse helps Republicans."},

  // ---- disclosure
  notice_24_48: {t: "24- and 48-hour reports", d: "Fast disclosure of independent expenditures. Until 20 days before the election, anyone whose spending on a race adds up to $10,000 must report within 48 hours. In the final stretch (Oct. 15 to Nov. 1 this year), it's $1,000 and 24 hours. The clock starts when the ad reaches the public, not when it's paid for. These notices are this tracker's main source."},
  periodic: {t: "Regular (periodic) reports", d: "The full reports every committee files. Candidates file quarterly (Apr. 15, Jul. 15, Oct. 15), plus pre-election and post-election reports. Party committees and PACs can file monthly. Donor lists and Schedule F coordinated spending appear only here."},
  f6: {t: "48-hour contribution notices", d: "In the last 20 days before an election (Oct. 15 to Nov. 1 this year), a candidate's campaign must report any single contribution of $1,000 or more within 48 hours on Form 6. These are the only near-real-time view of candidate fundraising late in the race. This page adds them on top of each nominee's last full report."},
  dissemination_date: {t: "Dissemination date", d: "The date an ad or mailer first reached the public. It starts the 24- or 48-hour reporting clock, and this page uses it to date spending. Filers sometimes report ahead of airing; dates later than today are shown as today."},
  schedule_e: {t: "Schedule E", d: "The FEC form section listing independent expenditures: who spent, on which candidate, supporting or opposing, how much and when."},
  schedule_f: {t: "Schedule F", d: "The FEC form section listing party coordinated expenditures. It appears only on a party's regular reports, not on 24- or 48-hour notices."},
  amendment: {t: "Amendments", d: "Filers often correct a report by filing an amended version, which replaces the original in full. This page keeps only the latest version, so a correction never gets added on top of the original."},

  // ---- this page's metrics
  helps: {t: "Helps Dems / Helps Reps", d: "All reported spending that works in a party's favor in this race: spending for its candidate plus spending against the other party's. The small line splits it into party committees and other outside groups."},
  party_vs_outside: {t: "Party vs. outside", d: "\"Party\" is money from party committees: their independent expenditures plus any coordinated spending ingested so far. \"Outside\" is everyone else: super PACs, traditional PACs and nonprofits."},
  offense: {t: "Offense and defense", d: "Money helping a party in a seat the other party holds now is offense; money in a seat it already holds is defense. A party spending mostly on offense believes it can gain seats. A party spending on defense is protecting what it has."},
  offense_share: {t: "Offense share", d: "Of all the money helping a party, the share spent in seats the other party holds. Seats where redistricting makes the current holder unclear are left out. House and Senate are shown separately because 435 House seats against 35 Senate seats would skew one combined number."},
  races_in_play: {t: "Races in play", d: "The number of races where spending helping that party has reached $100,000. A rough measure of how wide each side's map is."},
  party_footprint: {t: "Party committee footprint", d: "The number of races where a party committee has spent at least $1 helping its side. Shows where the parties themselves, not allied groups, have committed money."},
  first_party_dollar: {t: "First party dollar", d: "The earliest date a party committee spent in the race. Roughly, when the race joined that party's target list."},
  momentum: {t: "Last 7 days", d: "Spending dated in the past week, by dissemination date. Shows where money is moving now, not what built up earlier."},
  receipts: {t: "Nominees raised", d: "Each nominee's total receipts for the 2025-26 cycle from their own FEC reports: contributions, plus loans and transfers. It includes money raised and spent during the primary. The report date for each nominee is shown in the race details. An asterisk means the nominee was inferred from fundraising and may be a primary loser."},
  coh: {t: "Cash on hand", d: "What the campaign had in the bank at the end of its latest report: the money still available for the general election."},
  nominee: {t: "How the nominee is chosen", d: "FEC summaries don't record who won a primary. This page treats the candidate targeted most by general-election outside money (at least $10,000) as the nominee. With no such spending, it uses the top fundraiser and marks it as inferred."},
  nominee_inferred: {t: "Inferred nominee", d: "No general-election outside money has targeted anyone yet, so the nominee shown is the party's top fundraiser in the race. That can be a primary loser, so treat these rows with care. They never trigger a split signal."},
  split_signal: {t: "Split signal", d: "Outside money favors one party while the nominees' own fundraising favors the other, each by at least $250,000. It can mean one party is relying on its candidate rather than outside groups, or that outside groups see something donors don't. Both nominees must be identified from general-election spending and have a report on file."},
  holder: {t: "Seat holder", d: "The party that holds the seat now, from the congress-legislators dataset. \"Open\" means the current holder isn't on the ballot for it."},
  holder_uncertain: {t: "Holder uncertain", d: "Mid-decade redistricting renumbered some districts, so the member who holds a district number today may be running somewhere else. When that happens, offense and defense can't be called reliably, so these seats are left out of offense share. Hover the tag for the specific reason."},
  alerts: {t: "New-race alerts", d: "A race's first crossing of $100,000 or $1 million helping a party, its first party-committee dollar, or a new split signal. Dated by when the money reached the public. Also available as an RSS feed."},
  held: {t: "Held rows", d: "Single line items of $5M or more in a House race, or $25M or more in a Senate race, are held back until the FEC's processed data confirms them. This cycle's filings already include several obvious data-entry errors of $1 billion or more."},
  race_note: {t: "Race note", d: "Context the filings can't show, such as a nominee replaced mid-race. Notes are written by hand and listed in the Race notes section."},
};

(() => {
  const G = window.GLOSSARY;
  const pop = document.createElement("div");
  pop.id = "pop";
  pop.setAttribute("role", "tooltip");
  document.body.append(pop);
  let pinned = null;

  const show = el => {
    const k = el.dataset.t, g = G[k];
    if (!g) return;
    pop.innerHTML = `<b>${g.t}</b><p>${g.d}</p><a href="#g-${k}">In the glossary →</a>`;
    pop.style.display = "block";
    const r = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8));
    const below = r.bottom + 8 + h < innerHeight;
    pop.style.left = `${left + scrollX}px`;
    pop.style.top = `${(below ? r.bottom + 8 : r.top - h - 8) + scrollY}px`;
    el.setAttribute("aria-describedby", "pop");
  };
  const hide = () => { pop.style.display = "none"; pinned = null; };

  document.addEventListener("mouseover", e => { const el = e.target.closest("[data-t]"); if (el && !pinned) show(el); });
  document.addEventListener("mouseout", e => { const el = e.target.closest("[data-t]"); if (el && !pinned && !e.relatedTarget?.closest?.("#pop")) pop.style.display = "none"; });
  pop.addEventListener("mouseleave", () => { if (!pinned) pop.style.display = "none"; });
  document.addEventListener("focusin", e => { const el = e.target.closest("[data-t]"); if (el) show(el); });
  document.addEventListener("focusout", e => { if (e.target.closest("[data-t]") && !pinned) pop.style.display = "none"; });
  // capture phase: a tap on a "?" inside a table row must not also expand the row
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-t]");
    if (el) {
      e.preventDefault(); e.stopPropagation();
      if (pinned === el) hide(); else { pinned = el; show(el); }
      return;
    }
    if (!e.target.closest("#pop")) hide();
  }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
  addEventListener("scroll", () => { if (!pinned) pop.style.display = "none"; }, {passive: true});

  window.renderGlossary = () => {
    const el = document.getElementById("glossary");
    if (!el) return;
    el.innerHTML = Object.entries(G).sort((a, b) => a[1].t.localeCompare(b[1].t))
      .map(([k, g]) => `<dt id="g-${k}">${g.t}</dt><dd>${g.d}</dd>`).join("");
  };
  // helpers used by the page's renderers
  window.tip = (k, label) => `<button type="button" class="i" data-t="${k}" aria-label="What is ${(G[k] || {}).t || k}?">?</button>`;
  // keeps the "?" on the same line as the label's last word
  window.withTip = (text, k) => text.replace(/(\S+)\s*$/, `<span style="white-space:nowrap">$1${window.tip(k)}</span>`);
  window.term = (k, text) => `<span class="term" tabindex="0" data-t="${k}">${text}</span>`;
})();
