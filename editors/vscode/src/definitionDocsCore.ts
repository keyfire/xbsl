// What F12 should do in an XBSL file, decided apart from VS Code so it can be tested.
//
// Go to Definition is answered from the project index, so a member of the PLATFORM -
// `ОтветHttp.КодСтатуса`, `СериализацияJson.ЗаписатьОбъект` - has no source to jump to and
// the editor said "no definition found". The documentation page IS the definition of such a
// member, and the panel already knows how to show it.
//
// The order matters: a real definition always wins, and when there is neither a definition
// nor a page the request is passed on to VS Code so IT reports the miss in its own words -
// an extension that swallows the command would look like a broken key.

export type DefinitionAction = "reveal" | "docs" | "passThrough";

export function chooseAction(found: number, pageId: string | null | undefined): DefinitionAction {
  if (found > 0) {
    return "reveal";
  }
  return pageId ? "docs" : "passThrough";
}
