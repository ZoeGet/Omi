import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

if (!window.matchMedia) {
  window.matchMedia = query => Object.assign(new EventTarget(), {
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
  }) as MediaQueryList;
}

afterEach(cleanup);
