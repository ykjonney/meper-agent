/**
 * Skill file tree — AntD Tree component for browsing directory files.
 */
import { Tree, Spin, Empty } from 'antd'
import { FolderOutlined, FileOutlined } from '@ant-design/icons'
import type { DataNode } from 'antd/es/tree'
import type { SkillFileTreeNode } from '../services/tools-api'

interface SkillFileTreeProps {
  tree: SkillFileTreeNode[] | undefined
  isLoading: boolean
  selectedPath: string | null
  onSelect: (path: string) => void
}

/**
 * Convert backend tree nodes to AntD Tree DataNode format.
 */
function toDataNodes(nodes: SkillFileTreeNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: n.key,
    title: (
      <span className="inline-flex items-center gap-1">
        {n.is_leaf ? <FileOutlined className="text-gray-400" /> : <FolderOutlined className="text-blue-500" />}
        <span>{n.title}</span>
      </span>
    ),
    isLeaf: n.is_leaf,
    children: n.children ? toDataNodes(n.children) : undefined,
  }))
}

export default function SkillFileTree({ tree, isLoading, selectedPath, onSelect }: SkillFileTreeProps) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spin size="small" />
      </div>
    )
  }

  if (!tree || tree.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="无文件（单文件模式）"
        className="py-8"
      />
    )
  }

  const dataNodes = toDataNodes(tree)

  // Expand all by default
  const allKeys = collectDirectoryKeys(tree)

  return (
    <div className="h-full overflow-auto">
      <Tree
        treeData={dataNodes}
        showLine={{ showLeafIcon: false }}
        defaultExpandedKeys={allKeys}
        selectedKeys={selectedPath ? [selectedPath] : []}
        onSelect={(keys) => {
          if (keys.length > 0) {
            const key = keys[0] as string
            onSelect(key)
          }
        }}
        className="skill-file-tree"
      />
    </div>
  )
}

/**
 * Collect all directory keys for default expansion.
 */
function collectDirectoryKeys(nodes: SkillFileTreeNode[]): string[] {
  const keys: string[] = []
  for (const n of nodes) {
    if (!n.is_leaf) {
      keys.push(n.key)
      if (n.children) {
        keys.push(...collectDirectoryKeys(n.children))
      }
    }
  }
  return keys
}
