import React, { memo } from 'react';
import { FixedSizeList as List } from 'react-window';
import AutoSizer from 'react-virtualized-auto-sizer';
import Message from './Message';
const cloud = import.meta.env.VITE_CLOUD_URL;

const MessageList = memo(({ messages, currentUser, ...props }) => {
  return (
    <div className="h-full w-full flex-1 overflow-hidden">
      <AutoSizer>
        {({ height, width }) => (
          <List
            height={height}
            width={width}
            itemCount={messages.length}
            itemSize={100}
            itemData={{
              messages,
              currentUser,
              ...props
            }}
            className="scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-transparent"
            overscanCount={5}
          >
            {({ data, index, style }) => (
              <div style={{
                ...style,
                paddingLeft: '16px',
                paddingRight: '16px'
              }}>
                <Message 
                  msg={data.messages[index]}
                  currentUser={data.currentUser}
                  {...data}
                />
              </div>
            )}
          </List>
        )}
      </AutoSizer>
    </div>
  );
});

export default MessageList;
