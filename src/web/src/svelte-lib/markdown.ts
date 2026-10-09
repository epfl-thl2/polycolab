import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkMath from 'remark-math';
import remarkRehype from 'remark-rehype';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import rehypeKatex from 'rehype-katex';
import rehypeStringify from 'rehype-stringify';
// Sanitize untrusted content before trusted KaTeX generates its MathML/styles.
const processor = unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkRehype)
  .use(rehypeSanitize, {
    ...defaultSchema,
    attributes: {
      ...defaultSchema.attributes,
      code: [
        ...(defaultSchema.attributes?.code ?? []),
        ['className', 'language-math', 'math-inline', 'math-display'],
      ],
    },
  })
  .use(rehypeKatex, { trust: false, strict: 'ignore' })
  .use(rehypeStringify);
export const renderMarkdown = (content: string) => String(processor.processSync(content));
