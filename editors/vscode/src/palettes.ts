// Палитры подсветки XBSL из популярных цветовых схем. Применяются точечно через
// editor.tokenColorCustomizations: правила адресуют только скоупы `*.xbsl`, поэтому
// глобальная тема редактора и остальные языки не затрагиваются. Свои правила помечаем
// именем с префиксом, чтобы уметь заменять и снимать их, не трогая чужие настройки.

import * as vscode from "vscode";

const RULE_PREFIX = "xbsl-palette";

// Группы скоупов грамматики, которым палитра назначает цвета.
const BUCKETS: Record<string, string[]> = {
  keyword: ["keyword.control.xbsl", "keyword.operator.word.xbsl"],
  storage: ["storage.type.xbsl", "storage.modifier.xbsl"],
  annotation: ["storage.type.annotation.xbsl"],
  string: ["string.quoted.double.xbsl"],
  escape: ["constant.character.escape.xbsl"],
  number: ["constant.numeric.xbsl"],
  constant: ["constant.language.xbsl"],
  type: ["support.class.xbsl"],
  varlang: ["variable.language.xbsl"],
  interp: ["variable.other.interpolation.xbsl"],
  comment: [
    "comment.line.double-slash.xbsl",
    "comment.block.xbsl",
    "comment.block.documentation.xbsl",
  ],
};

interface BucketColor {
  fg: string;
  style?: string; // fontStyle: "italic", "bold", ...
}

interface Palette {
  label: string;
  detail: string;
  colors?: Record<string, BucketColor>; // нет = снять переопределения (тема редактора)
}

// Цвета взяты из канонических значений соответствующих тем.
const PALETTES: Palette[] = [
  {
    label: "Тема редактора",
    detail: "Снять переопределения – XBSL красится активной темой VS Code",
  },
  {
    label: "1С:Элемент (веб-среда)",
    detail: "Красные ключевые слова, синие строки – как в среде разработки платформы",
    colors: {
      keyword: { fg: "#F14C4C" },
      storage: { fg: "#F14C4C" },
      annotation: { fg: "#DCDCAA" },
      string: { fg: "#569CD6" },
      escape: { fg: "#9CDCFE" },
      number: { fg: "#B5CEA8" },
      constant: { fg: "#569CD6" },
      type: { fg: "#4EC9B0" },
      varlang: { fg: "#9CDCFE" },
      interp: { fg: "#9CDCFE" },
      comment: { fg: "#6A9955" },
    },
  },
  {
    label: "One Dark",
    detail: "Палитра Atom One Dark",
    colors: {
      keyword: { fg: "#C678DD" },
      storage: { fg: "#C678DD" },
      annotation: { fg: "#E5C07B" },
      string: { fg: "#98C379" },
      escape: { fg: "#56B6C2" },
      number: { fg: "#D19A66" },
      constant: { fg: "#D19A66" },
      type: { fg: "#E5C07B" },
      varlang: { fg: "#E06C75" },
      interp: { fg: "#E06C75" },
      comment: { fg: "#5C6370", style: "italic" },
    },
  },
  {
    label: "Monokai",
    detail: "Классическая палитра Monokai",
    colors: {
      keyword: { fg: "#F92672" },
      storage: { fg: "#F92672" },
      annotation: { fg: "#A6E22E" },
      string: { fg: "#E6DB74" },
      escape: { fg: "#AE81FF" },
      number: { fg: "#AE81FF" },
      constant: { fg: "#AE81FF" },
      type: { fg: "#66D9EF" },
      varlang: { fg: "#FD971F" },
      interp: { fg: "#FD971F" },
      comment: { fg: "#75715E" },
    },
  },
  {
    label: "Dracula",
    detail: "Палитра Dracula",
    colors: {
      keyword: { fg: "#FF79C6" },
      storage: { fg: "#FF79C6" },
      annotation: { fg: "#50FA7B" },
      string: { fg: "#F1FA8C" },
      escape: { fg: "#FF79C6" },
      number: { fg: "#BD93F9" },
      constant: { fg: "#BD93F9" },
      type: { fg: "#8BE9FD" },
      varlang: { fg: "#BD93F9" },
      interp: { fg: "#FFB86C" },
      comment: { fg: "#6272A4", style: "italic" },
    },
  },
  {
    label: "GitHub Dark",
    detail: "Палитра GitHub Dark",
    colors: {
      keyword: { fg: "#FF7B72" },
      storage: { fg: "#FF7B72" },
      annotation: { fg: "#D2A8FF" },
      string: { fg: "#A5D6FF" },
      escape: { fg: "#79C0FF" },
      number: { fg: "#79C0FF" },
      constant: { fg: "#79C0FF" },
      type: { fg: "#FFA657" },
      varlang: { fg: "#FFA657" },
      interp: { fg: "#FFA657" },
      comment: { fg: "#8B949E" },
    },
  },
];

interface TextMateRule {
  name?: string;
  scope: string | string[];
  settings: { foreground?: string; fontStyle?: string };
}

function buildRules(palette: Palette): TextMateRule[] {
  const rules: TextMateRule[] = [];
  for (const [bucket, color] of Object.entries(palette.colors ?? {})) {
    const scopes = BUCKETS[bucket];
    if (!scopes) {
      continue;
    }
    const settings: TextMateRule["settings"] = { foreground: color.fg };
    if (color.style) {
      settings.fontStyle = color.style;
    }
    rules.push({ name: `${RULE_PREFIX}: ${palette.label} – ${bucket}`, scope: scopes, settings });
  }
  return rules;
}

// Подменяет НАШИ правила в editor.tokenColorCustomizations, сохраняя чужие настройки
// пользователя (правила без нашего префикса и остальные ключи объекта).
async function applyPalette(palette: Palette): Promise<void> {
  const editorCfg = vscode.workspace.getConfiguration("editor");
  const current = editorCfg.get<Record<string, unknown>>("tokenColorCustomizations") ?? {};
  const next: Record<string, unknown> = { ...current };
  const existing = Array.isArray(next["textMateRules"]) ? (next["textMateRules"] as TextMateRule[]) : [];
  const foreign = existing.filter((r) => !(typeof r?.name === "string" && r.name.startsWith(RULE_PREFIX)));
  const ours = palette.colors ? buildRules(palette) : [];
  const merged = [...foreign, ...ours];
  if (merged.length > 0) {
    next["textMateRules"] = merged;
  } else {
    delete next["textMateRules"];
  }
  const value = Object.keys(next).length > 0 ? next : undefined;
  await editorCfg.update("tokenColorCustomizations", value, vscode.ConfigurationTarget.Global);
}

export function registerPalettePicker(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.choosePalette", async () => {
      const picked = await vscode.window.showQuickPick(
        PALETTES.map((p) => ({ label: p.label, detail: p.detail, palette: p })),
        { title: "Палитра кода XBSL", placeHolder: "Цвета применяются только к XBSL, тема редактора не меняется" }
      );
      if (!picked) {
        return;
      }
      await applyPalette(picked.palette);
      void vscode.window.showInformationMessage(
        picked.palette.colors
          ? `XBSL: палитра "${picked.palette.label}" применена.`
          : "XBSL: переопределения сняты, действует тема редактора."
      );
    })
  );
}
