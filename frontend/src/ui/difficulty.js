const MIN_LEVEL = 1;
const MAX_LEVEL = 10;

let container, arrow, valueText, scaleBox;

export function initDifficulty() {
  container = document.querySelector('.difficulty-container');
  arrow = document.getElementById('diffArrow');
  valueText = document.getElementById('diffValue');
  scaleBox = document.getElementById('diffScale');

  createScale();
}

function createScale() {
  scaleBox.innerHTML = Array.from(
    { length: MAX_LEVEL },
    (_, i) => `<span class="scale-num">${i + 1}</span>`
  ).join('');
}

export function setDifficulty(value) {
  const numericValue = Number(value);
  const displayValue = Number.isFinite(numericValue) ? numericValue : MIN_LEVEL;
  const positionValue = Math.max(MIN_LEVEL, Math.min(MAX_LEVEL, displayValue));
  const percent = ((positionValue - MIN_LEVEL) / (MAX_LEVEL - MIN_LEVEL)) * 100;

  arrow.style.left = `${percent}%`;
  valueText.style.left = `${percent}%`;
  valueText.textContent = displayValue.toFixed(2);
  container.style.display = 'block';
}
