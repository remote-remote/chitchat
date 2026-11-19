// Code fences and inline code are left alone so text about the tags still shows them.
const CODE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/
const TAG = /<\/?(?:speak|announce)>/gi
// While a reply streams in, its last characters can be the start of a tag.
const PARTIAL = /<\/?(?:s(?:p(?:e(?:a(?:k)?)?)?)?|a(?:n(?:n(?:o(?:u(?:n(?:c(?:e)?)?)?)?)?)?)?)?$/i

export function stripVoiceTags(text: string): string {
  if (!text.includes("<")) return text
  const parts = text.split(CODE)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part
      const stripped = part.replace(TAG, '')
      return i === parts.length - 1 ? stripped.replace(PARTIAL, '') : stripped
    })
    .join('')
}
