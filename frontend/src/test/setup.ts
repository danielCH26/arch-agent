import '@testing-library/jest-dom'

// jsdom does not implement `scrollIntoView`, which ChatWindow calls in a
// useEffect after every render. Without this stub, every ChatWindow test
// throws a TypeError. The stub is a no-op so the effect body just runs and
// returns.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {
    return undefined
  }
}