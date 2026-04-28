if (
  typeof globalThis.localStorage !== "undefined" &&
  typeof globalThis.localStorage.getItem !== "function"
) {
  const data = new Map();
  globalThis.localStorage = {
    getItem: (key) => {
      const value = data.get(String(key));
      return value === undefined ? null : value;
    },
    setItem: (key, value) => {
      data.set(String(key), String(value));
    },
    removeItem: (key) => {
      data.delete(String(key));
    },
    clear: () => {
      data.clear();
    },
    key: (index) => {
      const keys = Array.from(data.keys());
      return keys[index] ?? null;
    },
    get length() {
      return data.size;
    },
  };
}
