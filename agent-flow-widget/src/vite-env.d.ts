// 静态资源模块声明：widget 未引用 vite/client 类型，手动声明图片导入，
// 供 `import logo from './x.png'` 通过 tsc 检查。
declare module '*.png' {
  const src: string;
  export default src;
}

declare module '*.jpg' {
  const src: string;
  export default src;
}

declare module '*.svg' {
  const src: string;
  export default src;
}
