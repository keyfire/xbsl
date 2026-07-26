// Component icons for the designer trees (docs/DESIGNER.md): the thin vscode wrapper
// over the pure type->codicon mapping of componentIconsCore.ts. Both the palette and the
// structure view take icons from here so one component type always renders with one icon.

import * as vscode from "vscode";
import { iconIdFor } from "./componentIconsCore";

// The tree icon of a component type. packageName - the ui-schema package when known;
// container - the schema-backed container flag (refines only the generic fallback).
export function iconFor(type: string, packageName?: string, container?: boolean): vscode.ThemeIcon {
  return new vscode.ThemeIcon(iconIdFor(type, packageName, container));
}
