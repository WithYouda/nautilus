import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

// Models also use LaTeX's \(…\) and \[…\]. Normalize only prose;
// fenced blocks and inline code must retain their literal source.
export function normalizeMathDelimiters(source: string): string {
  let fence: { char: string; length: number } | null = null;
  const lines = source.split(/(?<=\n)/);
  let result = "";
  let prose = "";
  function flush() {
    let index = 0;
    while (index < prose.length) {
      if (prose[index] === "`") {
        const run = /^`+/.exec(prose.slice(index))![0];
        let end = prose.indexOf(run, index + run.length);
        while (end >= 0 && (prose[end - 1] === "`" || prose[end + run.length] === "`")) {
          end = prose.indexOf(run, end + run.length);
        }
        if (end >= 0) {
          result += prose.slice(index, end + run.length);
          index = end + run.length;
          continue;
        }
      }
      const opener = prose.slice(index, index + 2);
      if (opener === "\\(" || opener === "\\[") {
        const end = prose.indexOf(opener === "\\(" ? "\\)" : "\\]", index + 2);
        if (end >= 0) {
          const math = prose.slice(index + 2, end).trim();
          result += opener === "\\(" ? `$${math}$` : `\n\n$$\n${math}\n$$\n\n`;
          index = end + 2;
          continue;
        }
      }
      if (prose.slice(index, index + 2) === "\\\\") {
        result += "\\\\";
        index += 2;
      } else result += prose[index++];
    }
    prose = "";
  }
  for (const line of lines) {
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)/.exec(line);
    if (fence) {
      result += line;
      if (marker && marker[1][0] === fence.char && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
    } else if (marker) {
      flush();
      fence = { char: marker[1][0], length: marker[1].length };
      result += line;
    } else if (/^(?: {4}|\t)/.test(line)) {
      flush();
      result += line;
    } else prose += line;
  }
  flush();
  return result;
}

export default function LearningMarkdown({ children }: { children: string }) {
  return <ReactMarkdown
    remarkPlugins={[remarkGfm, remarkMath]}
    rehypePlugins={[[rehypeKatex, { trust: false, strict: "ignore", throwOnError: false, maxExpand: 1000 }]]}
    components={{ a: ({ children: label, ...props }) => <a {...props} target="_blank" rel="noreferrer">{label}</a> }}
  >{normalizeMathDelimiters(children)}</ReactMarkdown>;
}
