console.log('Agent Chat Widget loaded');

// 暴露全局 API
(window as any).AgentChat = {
  init: (config: any) => {
    console.log('AgentChat.init called with:', config);
  },
};
