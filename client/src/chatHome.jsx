import React from 'react'

const chatHome = () => {
  return (
    <div className="h-screen flex flex-col md:flex-row bg-background text-foreground">
      <div className="w-full md:w-1/3 border-r border-border bg-card">
        <div className="flex items-center p-4">
          <input type="text" placeholder="Search users" className="w-full p-2 bg-input border border-border rounded-lg" />
        </div>
        <div className="overflow-auto h-full">
          <div className="p-4 flex items-center space-x-4 hover:bg-muted cursor-pointer">
            <img src="https://placehold.co/40x40" alt="User 1" className="w-10 h-10 rounded-full" />
            <div>
              <div className="font-semibold">User 1</div>
              <div className="text-muted-foreground">Last message preview...</div>
            </div>
          </div>
          <div className="p-4 flex items-center space-x-4 hover:bg-muted cursor-pointer">
            <img src="https://placehold.co/40x40" alt="User 2" className="w-10 h-10 rounded-full" />
            <div>
              <div className="font-semibold">User 2</div>
              <div className="text-muted-foreground">Last message preview...</div>
            </div>
          </div>
        </div>
      </div>

      <div className="w-full md:w-2/3 flex flex-col">
        <div className="flex items-center p-4 border-b border-border bg-card">
          <img src="https://placehold.co/40x40" alt="Chat User" className="w-10 h-10 rounded-full" />
          <div className="ml-4">
            <div className="font-semibold">Chat User</div>
            <div className="text-muted-foreground">Online</div>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4 bg-background">
          <div className="flex flex-col space-y-4">
            <div className="self-start bg-primary text-primary-foreground py-2 px-4 rounded-lg max-w-lg">Hello!</div>
            <div className="self-end bg-secondary text-secondary-foreground py-2 px-4 rounded-lg max-w-lg">Hey there!</div>
          </div>
        </div>
        <div className="p-4 border-t border-border bg-card">
          <input type="text" placeholder="Type a message" className="w-full p-2 bg-input border border-border rounded-lg" />
        </div>
      </div>
    </div>
  )
}

export default chatHome
