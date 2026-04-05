import { Color } from '@tiptap/extension-color';
import ListItem from '@tiptap/extension-list-item';
import TextStyle from '@tiptap/extension-text-style';
import { EditorProvider, useCurrentEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import React from 'react';

const MenuBar = () => {
  const { editor } = useCurrentEditor();

  if (!editor) {
    return null;
  }

  return (
    <div className="flex gap-2 p-2 shadow-sm border-b border-gray-200 ">
      <button
        onClick={() => editor.chain().focus().toggleBold().run()}
        disabled={!editor.can().chain().focus().toggleBold().run()}
        className={`p-2 rounded ${editor.isActive('bold') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>B</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleItalic().run()}
        disabled={!editor.can().chain().focus().toggleItalic().run()}
        className={`p-2 rounded ${editor.isActive('italic') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>I</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleStrike().run()}
        disabled={!editor.can().chain().focus().toggleStrike().run()}
        className={`p-2 rounded ${editor.isActive('strike') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>S</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleCode().run()}
        disabled={!editor.can().chain().focus().toggleCode().run()}
        className={`p-2 rounded ${editor.isActive('code') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>{`</>`}</span>
      </button>
      <button
        onClick={() => editor.chain().focus().unsetAllMarks().run()}
        className="p-2 rounded hover:bg-gray-200"
      >
        <span>X</span>
      </button>
      <button
        onClick={() => editor.chain().focus().setParagraph().run()}
        className={`p-2 rounded ${editor.isActive('paragraph') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>P</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
        className={`p-2 rounded ${editor.isActive('heading', { level: 1 }) ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>H1</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        className={`p-2 rounded ${editor.isActive('heading', { level: 2 }) ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>H2</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        className={`p-2 rounded ${editor.isActive('bulletList') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>•</span>
      </button>
      <button
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        className={`p-2 rounded ${editor.isActive('orderedList') ? 'bg-gray-300' : 'hover:bg-gray-200'}`}
      >
        <span>1.</span>
      </button>
      <button
        onClick={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().chain().focus().undo().run()}
        className="p-2 rounded hover:bg-gray-200"
      >
        <span>↺</span>
      </button>
      <button
        onClick={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().chain().focus().redo().run()}
        className="p-2 rounded hover:bg-gray-200"
      >
        <span>↻</span>
      </button>
    </div>
  );
};

const extensions = [
  Color.configure({ types: [TextStyle.name, ListItem.name] }),
  TextStyle.configure({ types: [ListItem.name] }),
  StarterKit.configure({
    bulletList: {
      keepMarks: true,
      keepAttributes: false,
    },
    orderedList: {
      keepMarks: true,
      keepAttributes: false,
    },
  }),
];

const content = `
<h2>
  Hi there,
</h2>
<p>
  This is a <em>basic</em> example of <strong>Tiptap</strong>. Sure, there are all kinds of basic text styles you’d probably expect from a text editor. But wait until you see the lists:
</p>
<ul>
  <li>
    That’s a bullet list with one …
  </li>
  <li>
    … or two list items.
  </li>
</ul>
<p>
  Isn’t that great? And all of that is editable. But wait, there’s more. Let’s try a code block:
</p>
<pre><code class="language-css">body {
  display: none;
}</code></pre>
<p>
  I know, I know, this is impressive. It’s only the tip of the iceberg though. Give it a try and click a little bit around. Don’t forget to check the other examples too.
</p>
<blockquote>
  Wow, that’s amazing. Good work, boy! 👏<br />
  — Mom
</blockquote>
`;

const Editor = () => {
  return (
    <EditorProvider
      slotBefore={<MenuBar />}
      extensions={extensions}
      content={content}
      className="tiptap-editor bg-white p-4 border border-gray-300 rounded-lg"
    />
  );
};

export default Editor;
