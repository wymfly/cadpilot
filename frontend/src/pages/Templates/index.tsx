import { useState } from 'react';
import TemplateList from './TemplateList.tsx';
import TemplateDetail from './TemplateDetail.tsx';
import TemplateEditor from './TemplateEditor.tsx';

type View = 'list' | 'detail' | 'editor';

export default function Templates() {
  const [view, setView] = useState<View>('list');
  const [selected, setSelected] = useState('');

  switch (view) {
    case 'list':
      return (
        <TemplateList
          onSelect={(name) => {
            setSelected(name);
            setView('detail');
          }}
          onCreate={() => {
            setSelected('');
            setView('editor');
          }}
        />
      );

    case 'detail':
      return (
        <TemplateDetail
          name={selected}
          onBack={() => setView('list')}
          onEdit={() => setView('editor')}
        />
      );

    case 'editor':
      return (
        <TemplateEditor
          name={selected || undefined}
          onBack={() => (selected ? setView('detail') : setView('list'))}
          onSave={() => {
            if (selected) {
              setView('detail');
            } else {
              setView('list');
            }
          }}
        />
      );
  }
}
