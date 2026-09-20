import './style.css';
import githubMarkUrl from '@primer/octicons/build/svg/mark-github-24.svg?url';
import { initDifficulty } from './ui/difficulty';
import { bindEvents } from './ui/events';

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('githubMark').src = githubMarkUrl;
  initDifficulty();
  bindEvents();
});
