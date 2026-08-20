/** 找出兩字串的共同前綴/後綴,中間就是差異段(給校正 diff 顯示用)。 */
export function diffParts(a: string, b: string) {
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let post = 0;
  while (
    post < a.length - pre &&
    post < b.length - pre &&
    a[a.length - 1 - post] === b[b.length - 1 - post]
  ) {
    post++;
  }
  return {
    pre: a.slice(0, pre),
    aMid: a.slice(pre, a.length - post),
    bMid: b.slice(pre, b.length - post),
    post: a.slice(a.length - post),
  };
}
