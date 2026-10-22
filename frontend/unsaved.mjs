// 与DOM无关的未保存状态注册表，便于验证多个编辑区域不会互相覆盖。
export function createUnsavedRegistry() {
  const sources = new Map();
  return {
    add(source) {
      const id = Symbol('unsaved'); sources.set(id, source);
      return {id, dispose: () => sources.delete(id)};
    },
    pending(scope) {
      return [...sources].filter(([id, source]) => (!scope || scope.id === id) && (source.isDirty() || source.isBusy?.()))
        .map(([id, source]) => ({id, ...source}));
    },
    discard(scope) {
      for (const [id, source] of [...sources]) if (!scope || scope.id === id) {
        sources.delete(id); source.onDiscard?.();
      }
    },
    clear() { sources.clear(); },
  };
}
