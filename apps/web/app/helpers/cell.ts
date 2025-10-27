import bs58 from "bs58";

export const isSolanaAddress = (address: string) => {
  // Check length
  if (address.length > 44 && address.length < 32) {
    return false;
  }

  // Check Base58 validity
  try {
    const decoded = bs58.decode(address);
    // Check if the decoded length is 32 bytes
    return decoded.length === 32;
  } catch (err) {
    // Invalid Base58 encoding
    return false;
  }
};
export const isSolanaSignature = (sig: string) => {
  // Check length
  if (sig.length > 88 && sig.length < 86) {
    return false;
  }

  // Check Base58 validity
  try {
    const decoded = bs58.decode(sig);
    // Check if the decoded length is 64 bytes
    return decoded.length === 64;
  } catch (err) {
    // Invalid Base58 encoding
    return false;
  }
};
export const maybeDate = (value: string): Date | null => {
  let possibleDate = null;
  try {
    const val = Date.parse(value);
    if (Number.isNaN(val)) {
      return null;
    }
    possibleDate = new Date(val);
    return possibleDate;
  } catch (e) {
    return null;
  }

  /*
  // Regex for 'YYYY-MM-DD HH:mm:ss'
  const dateTimeRegex = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

  if (!dateTimeRegex.test(value)) {
    return null;
  }

  // Try to parse the string into a valid Date object
  const [datePart, timePart] = value.split(" ");
  if (!datePart || !timePart) {
    return null;
  }
  const [year, month, day] = datePart.split("-").map(Number);
  const [hours, minutes, seconds] = timePart.split(":").map(Number);

  // Month in Date constructor is zero-based (0 = January, 11 = December)
  if (!year || !month || !day || !hours || !minutes || !seconds) {
    return null;
  }
  const date = new Date(year, month - 1, day, hours, minutes, seconds);

  // Validate that the parsed date matches the input
  return date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day &&
    date.getHours() === hours &&
    date.getMinutes() === minutes &&
    date.getSeconds() === seconds
    ? new Date(date)
    : null;

   */
};
export const isNumber = (value: string = "") => !Number.isNaN(Number(value));
