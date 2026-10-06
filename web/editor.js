// Editor WYSIWYG (Tiptap, servido localmente de /static/vendor). Atalhos no estilo do Notion:
//   Ctrl+B negrito · Ctrl+I itálico · Ctrl+U sublinhado · Ctrl+Shift+S tachado · Ctrl+E código
//   Ctrl+K link · Ctrl+Shift+8 lista · Ctrl+Shift+7 lista numerada · Ctrl+Alt+1..3 títulos
//   Markdown ao digitar: "# " título · "- " ou "* " lista · "1. " lista numerada · "> " citação · **negrito**
import { Editor } from "/static/vendor/esm/@tiptap/core@3.31.4/es2022/core.mjs";
import { StarterKit } from "/static/vendor/esm/@tiptap/starter-kit@3.31.4/es2022/starter-kit.mjs";
import { Placeholder } from "/static/vendor/esm/@tiptap/extensions@3.31.4/es2022/extensions.mjs";

/**
 * @param {HTMLElement} element contêiner onde o editor é montado
 * @param {{placeholder?: string, onChange?: () => void, onSubmit?: () => void}} options
 *        onSubmit é chamado em Ctrl+Enter (usado na caixa de resposta).
 */
export function createEditor(element, { placeholder = "", onChange = () => {}, onSubmit = null } = {}) {
  const editor = new Editor({
    element,
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3, 4] },
        link: { openOnClick: false, autolink: true, HTMLAttributes: { target: "_blank", rel: "noopener noreferrer" } },
      }),
      Placeholder.configure({ placeholder }),
    ],
    content: "",
    editorProps: {
      attributes: { spellcheck: "true" },
      handleKeyDown(view, event) {
        const mod = event.ctrlKey || event.metaKey;
        if (mod && event.key.toLowerCase() === "k" && !event.shiftKey) {
          event.preventDefault();
          const previous = editor.getAttributes("link").href || "";
          const url = window.prompt("Endereço do link (vazio remove o link):", previous);
          if (url === null) return true;
          const chain = editor.chain().focus().extendMarkRange("link");
          (url.trim() ? chain.setLink({ href: url.trim() }) : chain.unsetLink()).run();
          return true;
        }
        if (mod && event.key === "Enter" && onSubmit) {
          event.preventDefault();
          onSubmit();
          return true;
        }
        return false;
      },
    },
    onUpdate: () => onChange(),
  });

  return {
    /** HTML do conteúdo; vazio ("") quando o editor está vazio (o Tiptap devolveria "<p></p>"). */
    getHTML: () => (editor.isEmpty ? "" : editor.getHTML()),
    setHTML: (html) => editor.commands.setContent(html || "", { emitUpdate: false }),
    setEditable: (editable) => {
      editor.setEditable(editable);
      element.classList.toggle("disabled", !editable);
    },
    isEmpty: () => editor.isEmpty,
    focus: () => editor.commands.focus("end"),
  };
}
