export function padZero(num) {
  return num < 10 ? "0" + num : String(num);
}

export function formatTime(date) {
  if (!date || isNaN(date)) return "";
  let hours = date.getHours();
  const minutes = padZero(date.getMinutes());
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${hours}:${minutes} ${ampm}`;
}
