import React from 'react';
import { FixedSizeList as List } from 'react-window';
import AutoSizer from 'react-virtualized-auto-sizer';
const cloud = import.meta.env.VITE_CLOUD_URL;

const VirtualizedChatMessages = ({ messages = [], currentUser, MemoizedMessage, chatWindowRef, onScroll }) => {
  return (
    <div 
      className="chat-window flex-1 overflow-y-auto py-1 px-1 md:px-4 bg-[#0a0a0a] relative" 
      ref={chatWindowRef} 
      onScroll={onScroll}
    >
      {messages.length ? (
        <AutoSizer>
          {({ height, width }) => (
            <List
              height={height}
              itemCount={messages.length}
              itemSize={80} // adjust height as needed
              width={width}
            >
              {({ index, style }) => (
                <div style={style}>
                  <MemoizedMessage key={messages[index].id} msg={messages[index]} currentUser={currentUser} />
                </div>
              )}
            </List>
          )}
        </AutoSizer>
      ) : (
        <div className="text-center text-gray-400 mt-4">No messages yet</div>
      )}
    </div>
  );
};

export default React.memo(VirtualizedChatMessages);
