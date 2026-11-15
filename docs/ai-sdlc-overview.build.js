// AI-SDLC concept deck — vendor-neutral overview for AI-curious external teams.
// Pure framework: NO internal metrics, project names, or "our stack" framing.
// Voice: conversational, plain, direct «вы», varied rhythm.
// Regenerate: scripts/build-decks.sh
const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.author = "AI-SDLC overview";
pres.title = "AI-SDLC — разработка с ИИ-агентами как дисциплина";

// ---- palette ----
const INK    = "0E1A33";
const NAVY   = "1E2A5A";
const NAVY2  = "1C2A52";
const TEAL   = "13B7A6"; // build / process
const AMBER  = "F5A524"; // gate / caution
const VIOLET = "8A7CF2"; // human / learning
const ICE    = "D7E3FB";
const PAPER  = "F4F7FB";
const CARD   = "FFFFFF";
const SLATE  = "5A6480";
const SLATE_L= "97A2C0";
const TXT    = "1A2440";

const HEAD = "Trebuchet MS";
const BODY = "Calibri";

const PW = 13.33, PH = 7.5, M = 0.7;
const CW = PW - 2 * M;
const PAGES = 26;

const cardShadow = () => ({ type: "outer", color: "20305C", blur: 10, offset: 3, angle: 135, opacity: 0.16 });

function bar(slide, color) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.18, h: PH, fill: { color } });
}
function footer(slide, n, onDark) {
  const c = onDark ? SLATE_L : SLATE;
  slide.addText("AI-SDLC · обзор", { x: 0.7, y: 7.05, w: 7, h: 0.3, fontFace: BODY, fontSize: 9, color: c, align: "left", margin: 0 });
  slide.addText(`${n} / ${PAGES}`, { x: PW - 2.0, y: 7.05, w: 1.3, h: 0.3, fontFace: BODY, fontSize: 9, color: c, align: "right", margin: 0 });
}
function header(slide, kicker, title, n, accent) {
  slide.background = { color: PAPER };
  bar(slide, accent || TEAL);
  slide.addText(kicker.toUpperCase(), { x: 0.7, y: 0.46, w: CW, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: accent || TEAL, charSpacing: 3, margin: 0 });
  slide.addText(title, { x: 0.7, y: 0.78, w: CW, h: 0.9, fontFace: HEAD, fontSize: 28, bold: true, color: INK, margin: 0 });
  footer(slide, n, false);
}
function darkHeader(slide, kicker, title, n, accent) {
  slide.background = { color: INK };
  bar(slide, accent || TEAL);
  slide.addText(kicker.toUpperCase(), { x: 0.7, y: 0.46, w: CW, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: accent || TEAL, charSpacing: 3, margin: 0 });
  slide.addText(title, { x: 0.7, y: 0.78, w: CW, h: 0.9, fontFace: HEAD, fontSize: 28, bold: true, color: "FFFFFF", margin: 0 });
  footer(slide, n, true);
}
function panel(slide, x, y, w, h, fill) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill || CARD }, shadow: cardShadow() });
}
function bulletsCard(slide, x, y, w, h, headerText, headerFill, items, code) {
  panel(slide, x, y, w, h, CARD);
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.6, fill: { color: headerFill } });
  slide.addText(headerText, { x: x + 0.05, y, w: w - 0.1, h: 0.6, fontFace: HEAD, fontSize: 13.5, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0 });
  slide.addText(items.map((t, i) => ({ text: t, options: { bullet: { code: code || "2022" }, breakLine: i < items.length - 1, paraSpaceAfter: 9 } })),
    { x: x + 0.32, y: y + 0.8, w: w - 0.6, h: h - 1.0, fontFace: BODY, fontSize: 14.5, color: TXT, margin: 0 });
}

// =====================================================================
// 1 — TITLE (dark)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: INK };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.22, h: PH, fill: { color: TEAL } });
  s.addText("AI-SDLC · ОБЗОР", { x: 0.9, y: 1.5, w: 9, h: 0.4, fontFace: HEAD, fontSize: 14, bold: true, color: TEAL, charSpacing: 4, margin: 0 });
  s.addText("Как наладить разработку,\nкогда код пишут агенты", { x: 0.86, y: 1.95, w: 11.2, h: 2.0, fontFace: HEAD, fontSize: 42, bold: true, color: "FFFFFF", lineSpacingMultiple: 1.03, margin: 0 });
  s.addText("Модели уже умные. Разберём, зачем тогда вообще процесс, какие в нём стадии, где нужен человек и как начать у себя.", { x: 0.9, y: 4.35, w: 10.2, h: 0.9, fontFace: BODY, fontSize: 17, color: ICE, lineSpacingMultiple: 1.12, margin: 0 });
  // motif: pipeline dots
  const dx = 9.7, dy = 5.5;
  const cols = [TEAL, TEAL, TEAL, AMBER, AMBER, AMBER, VIOLET];
  for (let i = 0; i < 7; i++) {
    s.addShape(pres.shapes.OVAL, { x: dx + i * 0.46, y: dy, w: 0.3, h: 0.3, fill: { color: cols[i] } });
    if (i < 6) s.addShape(pres.shapes.LINE, { x: dx + 0.3 + i * 0.46, y: dy + 0.15, w: 0.16, h: 0, line: { color: SLATE_L, width: 1 } });
  }
  s.addText("Обзор для команд, которые только присматриваются к ИИ", { x: 0.9, y: 6.5, w: 9, h: 0.3, fontFace: BODY, fontSize: 12, color: SLATE_L, margin: 0 });
}

// =====================================================================
// 2 — THE SHIFT
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Контекст", "ИИ перестал подсказывать и начал делать", 2);
  const cols = [
    { t: "Было", sub: "ИИ как автодополнение", b: ["подсказывает строки", "человек пишет и собирает всё сам", "упираемся в скорость набора кода"], fill: NAVY, txt: ICE },
    { t: "Стало", sub: "ИИ как исполнитель задач", b: ["читает репозиторий, правит файлы", "гоняет тесты, открывает PR", "один человек ведёт стаю агентов"], fill: TEAL, txt: ICE },
  ];
  const cw = 5.75, y = 2.0, h = 3.4;
  cols.forEach((c, i) => {
    const x = 0.7 + i * (cw + 0.43);
    panel(s, x, y, cw, h, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 0.78, fill: { color: c.fill } });
    s.addText(c.t, { x: x + 0.3, y: y + 0.08, w: cw - 0.6, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(c.sub, { x: x + 0.3, y: y + 0.44, w: cw - 0.6, h: 0.32, fontFace: BODY, fontSize: 12.5, italic: true, color: c.txt, margin: 0 });
    s.addText(c.b.map((t, j) => ({ text: t, options: { bullet: { code: "2022" }, breakLine: j < c.b.length - 1, paraSpaceAfter: 10 } })),
      { x: x + 0.35, y: y + 1.05, w: cw - 0.65, h: h - 1.2, fontFace: BODY, fontSize: 15, color: TXT, margin: 0 });
  });
  s.addText("Написать код теперь легко. Труднее другое: поверить, что пачка задач сделана правильно.", { x: 0.7, y: 5.7, w: CW, h: 0.5, fontFace: BODY, fontSize: 16, bold: true, color: NAVY, align: "center", margin: 0 });
}

// =====================================================================
// 3 — PROBLEM
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Проблема", "Модель умная, а доставка всё равно непредсказуемая", 3, AMBER);
  s.addText("Подход «кинул промпт и надеешься» не тянет поток задач. Вот что начинает ломаться:", { x: 0.7, y: 1.75, w: CW, h: 0.4, fontFace: BODY, fontSize: 16, color: SLATE, margin: 0 });
  const items = [
    ["Нет общей планки", "результат каждой задачи проверяют как придётся"],
    ["Бюджет уходит вслепую", "токены и лимиты тратятся, а сколько — заранее не ясно"],
    ["Ошибки повторяются", "одни и те же баги вылезают раз за разом"],
    ["Ревью защищает свой код", "та сессия, что писала, скорее оправдает код, чем найдёт дыру"],
    ["Нечем доказать", "работает или нет — непонятно, метрик нет, одни ощущения"],
  ];
  const cw = (CW - 4 * 0.3) / 5, y = 2.4, h = 3.1;
  items.forEach((it, i) => {
    const x = 0.7 + i * (cw + 0.3);
    panel(s, x, y, cw, h, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 0.1, fill: { color: AMBER } });
    s.addText(String(i + 1), { x: x + 0.2, y: y + 0.3, w: cw - 0.4, h: 0.6, fontFace: HEAD, fontSize: 30, bold: true, color: AMBER, margin: 0 });
    s.addText(it[0], { x: x + 0.22, y: y + 1.0, w: cw - 0.4, h: 0.7, fontFace: HEAD, fontSize: 14.5, bold: true, color: INK, margin: 0 });
    s.addText(it[1], { x: x + 0.22, y: y + 1.7, w: cw - 0.42, h: 1.3, fontFace: BODY, fontSize: 12, color: TXT, margin: 0 });
  });
  s.addText("Сама модель тут ни при чём. Не хватает процесса вокруг неё.", { x: 0.7, y: 5.75, w: CW, h: 0.4, fontFace: HEAD, fontSize: 17, bold: true, color: AMBER, align: "center", margin: 0 });
}

// =====================================================================
// 4 — DO WE NEED IT (key) — two columns
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Главный вопрос", "Модели поумнели — тогда зачем процесс?", 4, VIOLET);
  const colW = 5.75, y = 1.95, h = 3.7;
  bulletsCard(s, 0.7, y, colW, h, "ЧТО ДАЁТ МОДЕЛЬ", NAVY,
    ["синтаксис и паттерны из коробки", "скорость и широта решений", "поднимает нижнюю планку качества"], "2022");
  bulletsCard(s, 0.7 + colW + 0.43, y, colW, h, "ЧТО ДОБАВЛЯЕТ ПРОЦЕСС", TEAL,
    ["повторяемость и общую планку качества", "бюджет и контроль расходов", "аудит решений и учёбу на ошибках"], "2713");
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: 5.85, w: CW, h: 0.85, fill: { color: VIOLET } });
  s.addText("Способный джуниор без понятных задач, без ревью и без памяти об ошибках всё равно выдаёт хаос. Процесс как раз и наводит здесь порядок.", { x: 1.0, y: 5.85, w: CW - 0.6, h: 0.85, fontFace: BODY, fontSize: 14.5, color: "FFFFFF", valign: "middle", margin: 0 });
}

// =====================================================================
// 5 — DEFINITION
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Определение", "Если в двух словах", 5);
  panel(s, 0.7, 1.9, CW, 1.5, NAVY);
  s.addText("Собрать из человека и ИИ-агентов команду, которая работает предсказуемо: у каждого своя роль, задачи лежат в репозитории, на каждом шаге автоматические проверки, а на ошибках система учится.", { x: 1.05, y: 1.9, w: CW - 0.7, h: 1.5, fontFace: HEAD, fontSize: 18, bold: true, color: "FFFFFF", valign: "middle", lineSpacingMultiple: 1.08, margin: 0 });
  s.addText("Главное здесь не код, который пишет агент. Главное, что задачи стабильно доходят до конца почти сами, а человека зовут только по делу.", { x: 0.7, y: 3.55, w: CW, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: SLATE, align: "center", margin: 0 });
  const pillars = [
    { t: "Роли", d: "у каждого своя зона, никто не делает всё", c: TEAL },
    { t: "Задачи в git", d: "лежат файлом в репозитории, рядом с кодом", c: NAVY },
    { t: "Гейты", d: "на каждом шаге проверка, а не вера на слово", c: AMBER },
    { t: "Учёба", d: "система учится на собственных ошибках", c: VIOLET },
  ];
  const cw = (CW - 3 * 0.3) / 4, y = 4.3, h = 2.0;
  pillars.forEach((p, i) => {
    const x = 0.7 + i * (cw + 0.3);
    panel(s, x, y, cw, h, CARD);
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.28, w: 0.5, h: 0.5, fill: { color: p.c } });
    s.addText(p.t, { x: x + 0.25, y: y + 0.9, w: cw - 0.5, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: INK, margin: 0 });
    s.addText(p.d, { x: x + 0.25, y: y + 1.28, w: cw - 0.45, h: 0.65, fontFace: BODY, fontSize: 12, color: SLATE, margin: 0 });
  });
}

// stage model (shared by overview flow + per-stage slides)
const STAGES = [
  { k: "Discovery", t: "Идея → backlog", accent: TEAL,
    what: "Обсуждаем, что нужно, пишем спеку и режем её на задачи. У каждой — приоритет, размер, зависимости и то, как проверять результат.",
    why: "Список задач лежит файлом в репозитории, рядом с кодом. Его читают и люди, и агенты, и скрипты: одна версия правды для всех.",
    human: "Ставит цель и расставляет приоритеты." },
  { k: "Readiness", t: "Готовность (DoR)", accent: TEAL,
    what: "Перед запуском задачу смотрит скрипт: формат на месте, размер не гигантский, зависимости существуют, есть чем проверить результат.",
    why: "Это жёсткий стоп. Недоделанную задачу отсекаем раньше, чем агент сожжёт на ней бюджет.",
    human: "Если проверка красная — поправляет задачу." },
  { k: "Implement", t: "Имплементация", accent: TEAL,
    what: "Агент получает только свою задачу, а не весь список. Несколько задач идут параллельно; если они лезут в одни файлы, разводим их по отдельным рабочим копиям.",
    why: "Меньше контекста — дешевле и меньше ошибок. А отдельные копии дают чистый merge, без мусора друг от друга.",
    human: "Обычно не вмешивается." },
  { k: "Verify", t: "Verify — проверки", accent: AMBER,
    what: "Прогоняем линтер, тесты и сборку. Пока они не зелёные, до ревью даже не доходим.",
    why: "Незачем тратить дорогое ИИ-ревью на то, что и так ловит линтер. Это факт от машины, а не вера на слово.",
    human: "—" },
  { k: "Review", t: "Review — ревью", accent: AMBER,
    what: "Баги ищут на свежую голову: ревьюер видит только diff, задачу и правила стека, но не то, как агент рассуждал, когда писал.",
    why: "Тот, кто писал, скорее оправдает свой код, чем найдёт в нём дыру. Поэтому смотрит другой.",
    human: "На рисковых изменениях — финальный ревьюер." },
  { k: "Verdict", t: "Вердикт и релиз", accent: AMBER,
    what: "Каждое ревью кончается понятным решением: принять, доработать, разбить, отложить или позвать человека. Дальше — коммит, отметка «готово», короткий отчёт.",
    why: "Никаких «ну, вроде ок». У каждого решения есть хозяин, и оно идёт в метрики.",
    human: "Человек нужен только на одном исходе — эскалации." },
  { k: "Retro", t: "Петля обучения", accent: VIOLET,
    what: "Решения пишутся в журнал. После партии — разбор; из него рождаются задачи на улучшение самого процесса, их делают, а урок кладут в общий список.",
    why: "Без этого уроки тонут в логах, и грабли повторяются. Как раз это и отличает команду от набора скриптов.",
    human: "Решает, какие уроки внедрять." },
];

// =====================================================================
// 6 — PIPELINE OVERVIEW
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Конвейер", "Путь задачи: от идеи до релиза и обратно к улучшениям", 6);
  const n = STAGES.length, gp = 0.18;
  const w = (CW - gp * (n - 1)) / n, y = 2.5, h = 1.5;
  STAGES.forEach((st, i) => {
    const x = 0.7 + i * (w + gp);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: CARD }, rectRadius: 0.07, shadow: cardShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.1, fill: { color: st.accent } });
    s.addText(String(i + 1), { x, y: y + 0.22, w, h: 0.4, fontFace: HEAD, fontSize: 17, bold: true, color: st.accent, align: "center", margin: 0 });
    s.addText(st.k, { x: x + 0.02, y: y + 0.66, w: w - 0.04, h: 0.7, fontFace: HEAD, fontSize: 12.5, bold: true, color: INK, align: "center", valign: "top", margin: 0 });
    if (i < n - 1) s.addText("›", { x: x + w - 0.02, y, w: gp + 0.04, h, fontFace: HEAD, fontSize: 20, bold: true, color: SLATE_L, align: "center", valign: "middle", margin: 0 });
  });
  // legend
  const leg = [["сборка", TEAL], ["гейты", AMBER], ["обучение", VIOLET]];
  leg.forEach((l, i) => {
    const lx = 0.85 + i * 2.3;
    s.addShape(pres.shapes.OVAL, { x: lx, y: 4.4, w: 0.26, h: 0.26, fill: { color: l[1] } });
    s.addText(l[0], { x: lx + 0.34, y: 4.37, w: 1.9, h: 0.34, fontFace: BODY, fontSize: 13, color: TXT, valign: "middle", margin: 0 });
  });
  s.addText("↩  после разбора рождаются задачи на улучшение процесса — и снова в начало", { x: 0.7, y: 5.1, w: CW, h: 0.4, fontFace: BODY, fontSize: 15, bold: true, color: VIOLET, align: "center", margin: 0 });
  s.addText("Список задач — одна правда для всех. На каждом шаге работает проверка, а не вера на слово.", { x: 0.7, y: 5.7, w: CW, h: 0.4, fontFace: BODY, fontSize: 14, italic: true, color: SLATE, align: "center", margin: 0 });
  s.addText("Незнакомые термины — в глоссарии в конце.", { x: 0.7, y: 6.25, w: CW, h: 0.3, fontFace: BODY, fontSize: 11.5, color: SLATE_L, align: "center", margin: 0 });
}

// =====================================================================
// 7..13 — PER-STAGE SLIDES
// =====================================================================
function rail(s, current, accent) {
  const n = STAGES.length, x0 = 8.6, gap = 0.62, y = 0.62;
  for (let i = 0; i < n; i++) {
    const x = x0 + i * gap;
    const on = i === current;
    s.addShape(pres.shapes.OVAL, { x, y: on ? y - 0.04 : y, w: on ? 0.34 : 0.22, h: on ? 0.34 : 0.22, fill: { color: on ? accent : "C9D3E6" } });
  }
}
STAGES.forEach((st, idx) => {
  const s = pres.addSlide();
  header(s, `Стадия ${idx + 1} / 7`, st.t, 7 + idx, st.accent);
  rail(s, idx, st.accent);
  // big number
  s.addShape(pres.shapes.OVAL, { x: 0.7, y: 2.05, w: 1.3, h: 1.3, fill: { color: st.accent } });
  s.addText(String(idx + 1), { x: 0.7, y: 2.05, w: 1.3, h: 1.3, fontFace: HEAD, fontSize: 52, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0 });
  s.addText(st.k, { x: 0.7, y: 3.45, w: 2.1, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: st.accent, align: "center", margin: 0 });
  // What card
  const cx = 2.5, cw = CW - (cx - 0.7);
  panel(s, cx, 2.0, cw, 1.7, CARD);
  s.addText("ЧТО ПРОИСХОДИТ", { x: cx + 0.3, y: 2.18, w: cw - 0.6, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: st.accent, charSpacing: 2, margin: 0 });
  s.addText(st.what, { x: cx + 0.3, y: 2.5, w: cw - 0.6, h: 1.1, fontFace: BODY, fontSize: 15.5, color: TXT, lineSpacingMultiple: 1.05, margin: 0 });
  // Why card
  panel(s, cx, 3.85, cw, 1.7, CARD);
  s.addText("ЗАЧЕМ ЭТО НУЖНО", { x: cx + 0.3, y: 4.03, w: cw - 0.6, h: 0.3, fontFace: HEAD, fontSize: 12, bold: true, color: NAVY, charSpacing: 2, margin: 0 });
  s.addText(st.why, { x: cx + 0.3, y: 4.35, w: cw - 0.6, h: 1.1, fontFace: BODY, fontSize: 15.5, color: TXT, lineSpacingMultiple: 1.05, margin: 0 });
  // Human strip
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: 5.75, w: CW, h: 0.7, fill: { color: st.human === "—" ? "E7EBF3" : "EFEAFB" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: 5.75, w: 0.12, h: 0.7, fill: { color: st.human === "—" ? SLATE_L : VIOLET } });
  s.addText([
    { text: "Где человек:  ", options: { bold: true, color: st.human === "—" ? SLATE : VIOLET } },
    { text: st.human === "—" ? "не нужен, стадия идёт сама" : st.human, options: { color: TXT } },
  ], { x: 1.0, y: 5.75, w: CW - 0.6, h: 0.7, fontFace: BODY, fontSize: 14.5, valign: "middle", margin: 0 });
});

// =====================================================================
// 14 — WHERE IS THE HUMAN (dark, violet)
// =====================================================================
{
  const s = pres.addSlide();
  darkHeader(s, "Человек", "А где во всём этом человек?", 14, VIOLET);
  s.addText("По умолчанию всё идёт само. Человека зовут только по короткому списку поводов:", { x: 0.7, y: 1.75, w: CW, h: 0.4, fontFace: BODY, fontSize: 16, color: ICE, margin: 0 });
  const esc = [
    "Необратимый бизнес-выбор", "Спорный вердикт (escalate)", "Высокий риск или безопасность",
    "План неоднозначный", "Когда сказали «спроси меня»", "Ошибку не откатить",
  ];
  const cw = (CW - 2 * 0.3) / 3, rh = 0.95, gy = 0.25, y0 = 2.35;
  esc.forEach((e, i) => {
    const x = 0.7 + (i % 3) * (cw + 0.3);
    const y = y0 + Math.floor(i / 3) * (rh + gy);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: rh, fill: { color: NAVY2 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.1, h: rh, fill: { color: VIOLET } });
    s.addText(e, { x: x + 0.3, y, w: cw - 0.5, h: rh, fontFace: HEAD, fontSize: 15, bold: true, color: "FFFFFF", valign: "middle", margin: 0 });
  });
  s.addText([
    { text: "Остальное агент делает сам. ", options: { bold: true, color: VIOLET } },
    { text: "Но каждое решение идёт в журнал, так что потом всё можно поднять и проверить. Человек задаёт, что и в каких рамках делать, а не кликает на каждый шаг.", options: { color: ICE } },
  ], { x: 0.7, y: 5.55, w: CW, h: 0.9, fontFace: BODY, fontSize: 15, align: "center", margin: 0 });
}

// =====================================================================
// 15 — REPLACE THE DEV CYCLE (mapping)
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Трансформация", "Что становится с привычными ролями", 15);
  const rows = [
    ["Аналитик / продакт", "ИИ ведёт discovery, человек расставляет приоритеты"],
    ["Разработчик", "агент-исполнитель: получил задачу — выдал diff"],
    ["QA", "автопроверки плюс ИИ-ревью на свежую голову"],
    ["Тимлид", "оркестратор: партии, гейты, бюджет, вердикты"],
    ["Процесс / ретро", "петля обучения с журналом решений"],
  ];
  s.addText("БЫЛО — РОЛЬ", { x: 0.95, y: 1.8, w: 4.6, h: 0.25, fontFace: HEAD, fontSize: 10.5, bold: true, color: SLATE, charSpacing: 2, margin: 0 });
  s.addText("СТАЛО — КАК В AI-SDLC", { x: 6.1, y: 1.8, w: 6.4, h: 0.25, fontFace: HEAD, fontSize: 10.5, bold: true, color: SLATE, charSpacing: 2, margin: 0 });
  const y0 = 2.1, rh = 0.72, rg = 0.1;
  rows.forEach((r, i) => {
    const y = y0 + i * (rh + rg);
    panel(s, 0.7, y, CW, rh, CARD);
    s.addText(r[0], { x: 0.95, y, w: 4.5, h: rh, fontFace: HEAD, fontSize: 15, bold: true, color: INK, valign: "middle", margin: 0 });
    s.addText("→", { x: 5.5, y, w: 0.5, h: rh, fontFace: HEAD, fontSize: 18, bold: true, color: TEAL, align: "center", valign: "middle", margin: 0 });
    s.addText(r[1], { x: 6.1, y, w: 6.4, h: rh, fontFace: BODY, fontSize: 14, color: TXT, valign: "middle", margin: 0 });
  });
  s.addText([
    { text: "За человеком остаётся ", options: { bold: true, color: TEAL } },
    { text: "смысл, приоритеты, эскалации и вкус. Думают по-прежнему люди; меняется только, кто делает и проверяет рутину.", options: {} },
  ], { x: 0.7, y: 6.35, w: CW, h: 0.4, fontFace: BODY, fontSize: 13.5, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 16 — WHAT TO MEASURE
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Метрики", "Как понять, что это вообще работает", 16);
  const ms = [
    ["Доля доработок", "(rework) — сколько задач вернулось на доработку: качество суждений ИИ"],
    ["Повторяемость", "(recurrence) — как часто всплывает тот же класс ошибок"],
    ["Улов гейтов", "(gate-catch) — сколько проблем ловят проверки до релиза"],
    ["Стоимость задачи", "бюджет (токены или деньги) на одну доставленную задачу"],
    ["Накладные расходы", "(overhead) — цена оркестрации против простого прогона"],
    ["Время до релиза", "(lead time) — от готовой задачи до выката"],
  ];
  const cw = (CW - 2 * 0.3) / 3, rh = 1.55, gy = 0.25, y0 = 2.0;
  ms.forEach((m, i) => {
    const x = 0.7 + (i % 3) * (cw + 0.3);
    const y = y0 + Math.floor(i / 3) * (rh + gy);
    panel(s, x, y, cw, rh, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 0.08, fill: { color: TEAL } });
    s.addText(m[0], { x: x + 0.28, y: y + 0.22, w: cw - 0.5, h: 0.4, fontFace: HEAD, fontSize: 16, bold: true, color: INK, margin: 0 });
    s.addText(m[1], { x: x + 0.28, y: y + 0.66, w: cw - 0.5, h: 0.8, fontFace: BODY, fontSize: 12.5, color: SLATE, margin: 0 });
  });
  s.addText("Важно: низкий процент доработок ещё не значит, что вы не повторяете ошибки. Это разные мерки — считайте повторяемость отдельно.", { x: 0.7, y: 5.95, w: CW, h: 0.5, fontFace: BODY, fontSize: 14, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 17 — ECONOMICS (honest, amber)
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Экономика", "Сколько это стоит, если честно", 17, AMBER);
  const colW = 5.75, y = 1.95, h = 3.5;
  bulletsCard(s, 0.7, y, colW, h, "ОТКУДА БЕРЁТСЯ СТОИМОСТЬ", NAVY,
    ["подписки или токены ИИ-агентов", "повторные проходы: проверки, ревью, доработки", "изоляция и параллелизм тоже стоят денег"], "2022");
  bulletsCard(s, 0.7 + colW + 0.43, y, colW, h, "ЧЕМ ДЕРЖАТЬ В РАМКАХ", AMBER,
    ["лимит окна и стоп до выжигания", "бронь бюджета под задачу", "автоповтор вместо потери работы"], "2713");
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: 5.65, w: CW, h: 0.85, fill: { color: AMBER } });
  s.addText("Честно: с оркестрацией выходит дороже, чем просто запустить агента. Это плата за гейты и предсказуемость. На одной задаче это лишнее. На потоке окупается качеством.", { x: 1.0, y: 5.65, w: CW - 0.6, h: 0.85, fontFace: BODY, fontSize: 14.5, bold: true, color: "3A2A05", valign: "middle", margin: 0 });
}

// =====================================================================
// 18 — ANTI-PATTERNS (dark)
// =====================================================================
{
  const s = pres.addSlide();
  darkHeader(s, "Грабли", "На какие грабли наступают почти все", 18, AMBER);
  const lessons = [
    ["Ложное «всё ок»", "если что-то выбирает инструмент по условию — пусть проверяет, что инструмент реально есть, и честно говорит «ничего не нашёл»"],
    ["Тихо отвалившаяся защита", "защита, которая молча выключилась (нет конфига, протух кеш), хуже, чем её отсутствие. Пусть громко жалуется"],
    ["Отчёты в стол", "журналы «на всякий случай» копятся на каждой партии. Заводите их под конкретную задачу, а не по расписанию"],
    ["Одно правило в пяти местах", "скопированное правило рано или поздно разъедется. Держите его в одном месте, на остальное — ссылки"],
    ["Ревью своими же глазами", "та же сессия оправдывает свой код. Баги ищите на свежую голову"],
    ["Контекст без границ", "дать агенту весь репозиторий вместо одной задачи — это дороже и больше ошибок. Сужайте до одной задачи"],
  ];
  const cw = (CW - 0.4) / 2, rh = 1.25, gy = 0.18, y0 = 1.9;
  lessons.forEach((l, i) => {
    const x = 0.7 + (i % 2) * (cw + 0.4);
    const y = y0 + Math.floor(i / 2) * (rh + gy);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: rh, fill: { color: NAVY2 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.1, h: rh, fill: { color: AMBER } });
    s.addText(l[0], { x: x + 0.3, y: y + 0.16, w: cw - 0.55, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: AMBER, margin: 0 });
    s.addText(l[1], { x: x + 0.3, y: y + 0.56, w: cw - 0.55, h: 0.62, fontFace: BODY, fontSize: 12.5, color: ICE, margin: 0 });
  });
}

// =====================================================================
// 19 — WHERE TO START: decisions before the pilot (key)
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "С чего начать", "Что решить до пилота", 19);
  const steps = [
    ["Поставьте цель и метрику", "скорость, стоимость или покрытие — решите заранее, что будет успехом"],
    ["Выберите, где пробовать", "внутренние инструменты, тесты, инфра-скрипты или внешняя разработка"],
    ["Определите бюджет", "подписки на N человек или API, потолок на пилот, кто платит"],
    ["Назначьте владельца", "один человек ведёт пилот и решает, масштабировать или нет"],
  ];
  const lx = 0.7, lw = 7.4, y0 = 1.95, sh = 1.0, sg = 0.18;
  steps.forEach((st, i) => {
    const y = y0 + i * (sh + sg);
    panel(s, lx, y, lw, sh, CARD);
    s.addShape(pres.shapes.OVAL, { x: lx + 0.2, y: y + (sh - 0.6) / 2, w: 0.6, h: 0.6, fill: { color: TEAL } });
    s.addText(String(i + 1), { x: lx + 0.2, y: y + (sh - 0.6) / 2, w: 0.6, h: 0.6, fontFace: HEAD, fontSize: 22, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0 });
    s.addText(st[0], { x: lx + 1.0, y: y + 0.17, w: lw - 1.2, h: 0.4, fontFace: HEAD, fontSize: 16, bold: true, color: INK, margin: 0 });
    s.addText(st[1], { x: lx + 1.0, y: y + 0.55, w: lw - 1.2, h: 0.42, fontFace: BODY, fontSize: 12.5, color: SLATE, margin: 0 });
  });
  const rx = 8.5, rw = 4.13;
  panel(s, rx, 1.95, rw, 4.72, VIOLET);
  s.addText("Зачем нужен пилот", { x: rx + 0.3, y: 2.2, w: rw - 0.6, h: 0.5, fontFace: HEAD, fontSize: 19, bold: true, color: "FFFFFF", margin: 0 });
  s.addText([
    { text: "прогнать 5–10 реальных задач через гейты", options: { bullet: { code: "2713" }, breakLine: true, paraSpaceAfter: 14 } },
    { text: "посчитать доработки и стоимость задачи", options: { bullet: { code: "2713" }, breakLine: true, paraSpaceAfter: 14 } },
    { text: "состояние в git — всё легко откатить", options: { bullet: { code: "2713" }, breakLine: true, paraSpaceAfter: 14 } },
    { text: "решать про масштаб по данным, а не по хайпу", options: { bullet: { code: "2713" } } },
  ], { x: rx + 0.35, y: 2.85, w: rw - 0.65, h: 3.6, fontFace: BODY, fontSize: 14, color: "FFFFFF", margin: 0 });
}

// =====================================================================
// 20 — PRACTICAL BARRIERS (access / InfoSec / legal)
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Доступ и ИБ", "Что лучше расшить заранее", 20, AMBER);
  const cards = [
    { t: "Доступ и оплата (РФ)", c: AMBER, b: "Из России напрямую купить и оплатить топ-модели нельзя. Решайте заранее с закупкой и юристами: зарубежное юрлицо или карта, доступ через облачных провайдеров или посредников, либо доступные и локальные модели для чувствительных задач." },
    { t: "ИБ: данные за периметром", c: NAVY, b: "У облачных агентов код и данные уходят наружу, а развернуть у себя обычно нельзя. Согласуйте с ИБ, что можно отдавать, а что нет (секреты, ПДн), список разрешённых инструментов и DLP. Появляются и новые риски: prompt-injection и supply-chain расширений." },
    { t: "Юристы и комплаенс", c: VIOLET, b: "Лицензии и условия инструментов, где лежат данные, отраслевые требования к ПДн. Зелёный свет от юристов до старта дешевле, чем стоп посреди пилота." },
  ];
  const cw = (CW - 2 * 0.3) / 3, y = 2.1, h = 3.75;
  cards.forEach((c, i) => {
    const x = 0.7 + i * (cw + 0.3);
    panel(s, x, y, cw, h, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 0.72, fill: { color: c.c } });
    s.addText(c.t, { x: x + 0.25, y, w: cw - 0.5, h: 0.72, fontFace: HEAD, fontSize: 15.5, bold: true, color: "FFFFFF", valign: "middle", margin: 0 });
    s.addText(c.b, { x: x + 0.28, y: y + 0.78, w: cw - 0.56, h: h - 0.95, fontFace: BODY, fontSize: 14, color: TXT, lineSpacingMultiple: 1.1, valign: "middle", margin: 0 });
  });
  s.addText("Эти три вопроса лучше закрыть на старте, а не посреди пилота.", { x: 0.7, y: 6.1, w: CW, h: 0.35, fontFace: BODY, fontSize: 13.5, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 21 — CALIBRATE SDLC BY TASK TYPE
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Калибровка под задачу", "Под разные задачи — разный процесс", 21);
  s.addText("Насколько строгий процесс — зависит от риска задачи, а не от «зрелости» команды. У разных задач может быть свой контур.", { x: 0.7, y: 1.72, w: CW, h: 0.35, fontFace: BODY, fontSize: 15, color: SLATE, margin: 0 });
  const cards = [
    { title: "Внутренние · низкий риск", c: TEAL,
      ex: "внутренние инструменты, скрипты, тесты, черновики, эксперименты",
      rows: [["Процесс", "лёгкий, можно отдельный короткий контур"], ["ИИ", "максимум автономии"], ["Человек", "иногда смотрит выборочно, ревью по желанию"]] },
    { title: "Прод · внешнее · высокий риск", c: NAVY,
      ex: "клиентский код, инфраструктура, релизы",
      rows: [["Процесс", "полный: verify → review → вердикт"], ["ИИ", "делает понятную рутину"], ["Человек", "заходит через чат или issue tracker, держит эскалации"]] },
  ];
  const colW = 5.75, y = 2.3, h = 3.65;
  cards.forEach((cd, i) => {
    const x = 0.7 + i * (colW + 0.43);
    panel(s, x, y, colW, h, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: colW, h: 0.66, fill: { color: cd.c } });
    s.addText(cd.title, { x: x + 0.3, y, w: colW - 0.6, h: 0.66, fontFace: HEAD, fontSize: 16, bold: true, color: "FFFFFF", valign: "middle", margin: 0 });
    s.addText([{ text: "Это про: ", options: { italic: true, bold: true, color: SLATE } }, { text: cd.ex, options: { italic: true, color: SLATE } }],
      { x: x + 0.3, y: y + 0.82, w: colW - 0.6, h: 0.55, fontFace: BODY, fontSize: 12.5, margin: 0 });
    cd.rows.forEach((r, j) => {
      const ry = y + 1.52 + j * 0.66;
      s.addText([{ text: r[0] + "   ", options: { bold: true, color: cd.c } }, { text: r[1], options: { color: TXT } }],
        { x: x + 0.3, y: ry, w: colW - 0.6, h: 0.62, fontFace: BODY, fontSize: 14, lineSpacingMultiple: 1.04, margin: 0 });
    });
  });
  s.addText("Начните с лёгкого контура на внутренних задачах, а строгий прод-цикл включайте там, где этого требует риск. Один процесс на всё либо тормозит мелочь, либо рискует на важном.", { x: 0.7, y: 6.15, w: CW, h: 0.6, fontFace: BODY, fontSize: 13.5, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 22 — CYCLE DEEPENS TOWARD PROD
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "От идеи до прода", "Чем ближе к проду, тем длиннее путь", 22, NAVY);
  s.addText("Прототип можно «собрал и попробовал». А до прода путь длиннее: больше стадий и больше проверок.", { x: 0.7, y: 1.72, w: CW, h: 0.35, fontFace: BODY, fontSize: 15, color: SLATE, margin: 0 });
  // internal short chain
  s.addText("ВНУТРЕННЕЕ · ПРОТОТИП", { x: 0.7, y: 2.28, w: 6, h: 0.28, fontFace: HEAD, fontSize: 11, bold: true, color: TEAL, charSpacing: 1.5, margin: 0 });
  const inn = ["Идея", "Сборка", "Готово"];
  const iw = 1.6, ig = 0.22, iy = 2.62, ih = 0.72;
  inn.forEach((t, i) => {
    const x = 0.7 + i * (iw + ig);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: iy, w: iw, h: ih, fill: { color: TEAL }, rectRadius: 0.06, shadow: cardShadow() });
    s.addText(t, { x, y: iy, w: iw, h: ih, fontFace: HEAD, fontSize: 13, bold: true, color: "FFFFFF", align: "center", valign: "middle", margin: 0 });
  });
  // prod long chain
  s.addText("ПРОД-РЕЛИЗ", { x: 0.7, y: 3.72, w: 6, h: 0.28, fontFace: HEAD, fontSize: 11, bold: true, color: NAVY, charSpacing: 1.5, margin: 0 });
  // gates (verify/review/вердикт from slide 6 & 21) shown in amber INSIDE the prod chain
  const prod = [
    { t: "Идея", g: false }, { t: "Анализ", g: false }, { t: "Разработка", g: false },
    { t: "Verify", g: true }, { t: "Review", g: true }, { t: "Вердикт", g: true },
    { t: "Релиз", g: false }, { t: "Мониторинг", g: false },
  ];
  const pn = prod.length, pg = 0.14, pw = (CW - pg * (pn - 1)) / pn, py = 4.06, ph2 = 0.82;
  prod.forEach((p, i) => {
    const x = 0.7 + i * (pw + pg);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: py, w: pw, h: ph2, fill: { color: p.g ? AMBER : NAVY }, rectRadius: 0.06, shadow: cardShadow() });
    s.addText(p.t, { x: x + 0.02, y: py, w: pw - 0.04, h: ph2, fontFace: HEAD, fontSize: 10.5, bold: true, color: p.g ? "3A2A05" : "FFFFFF", align: "center", valign: "middle", margin: 0 });
  });
  panel(s, 0.7, 5.3, CW, 1.36, CARD);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.7, y: 5.3, w: 0.12, h: 1.36, fill: { color: NAVY } });
  s.addText([
    { text: "Это та же петля со слайда 6, просто для прода она длиннее. Гейты ", options: { color: TXT } },
    { text: "verify → review → вердикт", options: { bold: true, color: "B8860B" } },
    { text: " остаются внутри, а вокруг добавляются анализ, релиз и мониторинг. И каждая стадия — это уже отдельная ", options: { color: TXT } },
    { text: "роль-агент", options: { bold: true, color: INK } },
    { text: " (аналитик, QA, безопасник, релиз) со своими скиллами. В индустрии это зовут AI-native SDLC и multi-agent role-системами (например, MetaGPT, CrewAI).", options: { color: TXT } },
  ], { x: 1.0, y: 5.42, w: CW - 0.6, h: 1.12, fontFace: BODY, fontSize: 13, valign: "middle", lineSpacingMultiple: 1.05, margin: 0 });
}

// =====================================================================
// 23 — TWO HUMAN CONTOURS
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Люди вокруг ИИ", "Чем больше делает ИИ, тем нужнее люди", 23, VIOLET);
  s.addText("Люди никуда не деваются, просто роль другая. Вокруг агентов появляются два контура:", { x: 0.7, y: 1.72, w: CW, h: 0.35, fontFace: BODY, fontSize: 15, color: SLATE, margin: 0 });
  const hcards = [
    { t: "Кто делает самих агентов", c: VIOLET,
      b: "Создают и улучшают агентов: их навыки-скиллы, проверки, гейты. Без этих людей система не растёт и потихоньку портится. В индустрии это называют LLMOps / AgentOps." },
    { t: "Кто проверяет за ИИ", c: NAVY,
      b: "Смотрят то, что выдал ИИ, на ключевых точках. Инженер всё меньше пишет сам и всё больше принимает работу. Чем выше риск, тем больше ручной приёмки — этого ждут и регуляторы." },
  ];
  const colW = 5.75, y = 2.55, h = 2.95;
  hcards.forEach((cd, i) => {
    const x = 0.7 + i * (colW + 0.43);
    panel(s, x, y, colW, h, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: colW, h: 0.72, fill: { color: cd.c } });
    s.addText(cd.t, { x: x + 0.3, y, w: colW - 0.6, h: 0.72, fontFace: HEAD, fontSize: 17, bold: true, color: "FFFFFF", valign: "middle", margin: 0 });
    s.addText(cd.b, { x: x + 0.3, y: y + 0.84, w: colW - 0.6, h: h - 1.02, fontFace: BODY, fontSize: 15, color: TXT, lineSpacingMultiple: 1.12, valign: "middle", margin: 0 });
  });
  s.addText("Раньше всё упиралось в написание кода. Теперь — в проверку и развитие. Рутину тянет ИИ, а за качество и рост системы отвечают люди.", { x: 0.7, y: 5.85, w: CW, h: 0.6, fontFace: BODY, fontSize: 14, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 24 — WHEN NOT NEEDED
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Границы", "А когда всё это не нужно", 24, AMBER);
  const items = [
    ["Разовая задача или прототип", "хватит агента в чате, лишние церемонии только мешают"],
    ["Нет потока задач", "не стройте платформу, пока нет очереди"],
    ["Нечего мерить", "если не меряете, не поймёте, стало ли лучше"],
    ["Ошибку не откатить", "там, где откат невозможен, автономию не отдают"],
  ];
  const cw = (CW - 0.4) / 2, rh = 1.6, gy = 0.3, y0 = 2.1;
  items.forEach((it, i) => {
    const x = 0.7 + (i % 2) * (cw + 0.4);
    const y = y0 + Math.floor(i / 2) * (rh + gy);
    panel(s, x, y, cw, rh, CARD);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.12, h: rh, fill: { color: AMBER } });
    s.addText(it[0], { x: x + 0.35, y: y + 0.25, w: cw - 0.6, h: 0.5, fontFace: HEAD, fontSize: 17, bold: true, color: INK, margin: 0 });
    s.addText(it[1], { x: x + 0.35, y: y + 0.82, w: cw - 0.6, h: 0.65, fontFace: BODY, fontSize: 14, color: SLATE, margin: 0 });
  });
  s.addText("Дисциплина не ради дисциплины. Заводите ровно тот гейт, которым реально кто-то будет пользоваться.", { x: 0.7, y: 6.2, w: CW, h: 0.4, fontFace: BODY, fontSize: 14.5, italic: true, color: SLATE, align: "center", margin: 0 });
}

// =====================================================================
// 25 — CLOSING (dark)
// =====================================================================
{
  const s = pres.addSlide();
  s.background = { color: INK };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.22, h: PH, fill: { color: TEAL } });
  s.addText("ИТОГ", { x: 0.9, y: 1.55, w: 9, h: 0.4, fontFace: HEAD, fontSize: 14, bold: true, color: TEAL, charSpacing: 4, margin: 0 });
  s.addText([
    { text: "Модель умная — спору нет.\n", options: { color: SLATE_L } },
    { text: "А порядок наводит процесс вокруг неё.", options: { color: "FFFFFF" } },
  ], { x: 0.86, y: 2.0, w: 11.3, h: 1.9, fontFace: HEAD, fontSize: 38, bold: true, lineSpacingMultiple: 1.05, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 0.9, y: 4.35, w: 4.0, h: 0, line: { color: TEAL, width: 2 } });
  s.addText("С чего начать: один пилот, задачи в файле, два гейта (verify и вердикт), и померяйте доработки и стоимость.", { x: 0.9, y: 4.6, w: 11.0, h: 0.7, fontFace: BODY, fontSize: 16, color: ICE, margin: 0 });
  s.addText("Масштабировать или нет — решайте по данным пилота, а не по хайпу.", { x: 0.9, y: 5.4, w: 11, h: 0.4, fontFace: BODY, fontSize: 14, italic: true, color: SLATE_L, margin: 0 });
  s.addText("Вопросы?", { x: 0.9, y: 6.0, w: 6, h: 0.6, fontFace: HEAD, fontSize: 24, bold: true, color: VIOLET, margin: 0 });
}

// =====================================================================
// 26 — GLOSSARY (appendix)
// =====================================================================
{
  const s = pres.addSlide();
  header(s, "Справочник", "Глоссарий простыми словами", 26);
  const left = [
    ["SDLC", "жизненный цикл ПО: от идеи до эксплуатации"],
    ["Backlog", "список задач; здесь — файл в репозитории"],
    ["DoR (готовность)", "критерии готовности задачи к запуску"],
    ["Verify", "автопроверки: линт, тесты, сборка"],
    ["Review (ревью)", "проверка изменений на ошибки в свежем контексте"],
    ["Verdict (вердикт)", "явный исход ревью: принять / доработать / разбить / отложить / эскалировать"],
    ["Rework (доработка)", "возврат задачи на повторную работу"],
    ["Скилл (skill)", "переиспользуемый навык-инструкция для агента, как плагин"],
    ["Task packet", "пакет одной задачи: только её контекст, не весь backlog"],
  ];
  const right = [
    ["Гейт", "обязательная контрольная точка"],
    ["Human-in-the-loop", "обязательная проверка и одобрение человеком"],
    ["Роль-агент", "ИИ-агент с заданной ролью (аналитик, разработчик, QA…)"],
    ["Оркестратор", "раздаёт задачи агентам, следит за гейтами и бюджетом"],
    ["LLMOps / AgentOps", "те, кто строит и развивает агентов и гейты"],
    ["Blast radius", "масштаб ущерба, если изменение пойдёт не так"],
    ["Prompt-injection", "подмена поведения агента вредоносным текстом в данных"],
    ["on-prem · ПДн", "развёртывание внутри периметра · персональные данные"],
  ];
  const renderCol = (col, x) => {
    const runs = [];
    col.forEach((e) => {
      runs.push({ text: e[0], options: { bold: true, color: NAVY } });
      runs.push({ text: "  —  " + e[1], options: { color: TXT, breakLine: true, paraSpaceAfter: 9 } });
    });
    s.addText(runs, { x, y: 1.9, w: 5.75, h: 4.8, fontFace: BODY, fontSize: 12, lineSpacingMultiple: 1.03, valign: "top", margin: 0 });
  };
  renderCol(left, 0.7);
  renderCol(right, 0.7 + 5.75 + 0.43);
}

pres.writeFile({ fileName: "ai-sdlc-overview.pptx" }).then(f => console.log("WROTE", f, "TOTAL slides expected", PAGES));
