import * as React from 'react';
import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import ShiftPortal from './components/ShiftPortal';

export default function App() {
  return (
    <FluentProvider theme={webLightTheme}>
      <ShiftPortal />
    </FluentProvider>
  );
}
