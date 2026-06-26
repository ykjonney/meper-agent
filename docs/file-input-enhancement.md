# 文件输入功能增强

## 问题描述

1. **文件变量缺少"必填"配置**：StartNode 的文件类型变量没有"是否必须"的配置选项
2. **测试运行时缺少文件上传**：执行测试时没有上传文件的入口，只能手动输入 FileRef ID

## 解决方案

### 1. 为文件类型添加"必填"配置

**文件**：`frontend/src/features/workflow-editor/utils/variable-types.ts`

在 `file` 类型的 `constraintFields` 中添加了 `required` 字段：

```typescript
file: {
  label: '文件',
  color: '#F97316',
  icon: '📄',
  description: '文件上传',
  constraintFields: [
    { name: 'required', label: '必填', valueType: 'boolean', defaultValue: false },  // ✅ 新增
    { name: 'allowed_extensions', label: '允许的扩展名', valueType: 'tags', defaultValue: [] },
    { name: 'max_size_mb', label: '最大大小 (MB)', valueType: 'number', defaultValue: null },
    { name: 'multiple', label: '允许多文件', valueType: 'boolean', defaultValue: false },
  ],
},
```

**效果**：用户在配置面板中编辑文件变量时，可以看到"必填"开关。

---

### 2. 在测试运行时实现文件上传

#### 2.1 创建通用文件上传 API

**新文件**：`frontend/src/services/files-api.ts`

提供通用的文件上传功能：

```typescript
export const filesApi = {
  upload(file, originKind, originId, onProgress),
  get(fileId),
  delete(fileId),
}
```

#### 2.2 实现文件上传组件

**文件**：`frontend/src/pages/workflow-detail-page.tsx`

在 `VariableFormField` 中添加了 `file` 类型的渲染逻辑：

```typescript
case 'file': {
  const multiple = variable.constraints?.multiple as boolean | undefined
  const allowedExts = variable.constraints?.allowed_extensions as string[] | undefined
  const maxSizeMb = variable.constraints?.max_size_mb as number | undefined

  // 文件上传处理
  const handleUpload = async (file: File) => {
    // 1. 验证文件大小
    if (maxBytes && file.size > maxBytes) {
      message.error(`文件 "${file.name}" 超过大小限制 (${maxSizeMb}MB)`)
      return false
    }

    // 2. 上传到文件库
    const ref = await filesApi.upload(file, 'workflow_input')
    const fileId = getFileId(ref)

    // 3. 更新表单值
    if (multiple) {
      const current = Array.isArray(value) ? value : []
      onChange([...current, fileId])
    } else {
      onChange(fileId)
    }
    message.success(`文件 "${file.name}" 上传成功`)
    return false
  }

  // 文件移除处理
  const handleRemove = (fileId: string) => {
    if (multiple) {
      const current = Array.isArray(value) ? value : []
      onChange(current.filter((id) => String(id) !== fileId))
    } else {
      onChange(null)
    }
  }

  // 渲染上传组件
  input = (
    <div className="space-y-1.5">
      <Upload
        beforeUpload={handleUpload}
        showUploadList={false}
        accept={accept}
        multiple={multiple}
        disabled={running}
      >
        <Button icon={<UploadOutlined />} size="small" loading={running}>
          {multiple ? '上传文件' : '选择文件'}
        </Button>
      </Upload>

      {/* 已上传文件列表 */}
      {fileIds.length > 0 && (
        <div className="space-y-1">
          {fileIds.map((fileId) => (
            <div key={fileId} className="flex items-center gap-2 px-2 py-1 bg-gray-50 rounded text-xs">
              <FileOutlined className="text-orange-500" />
              <span className="flex-1 truncate font-mono" title={fileId}>
                {fileId}
              </span>
              <Tooltip title="移除">
                <Button
                  type="text"
                  size="small"
                  icon={<DeleteOutlined />}
                  danger
                  onClick={() => handleRemove(fileId)}
                  disabled={running}
                />
              </Tooltip>
            </div>
          ))}
        </div>
      )}
    </div>
  )
  break
}
```

**功能特性**：

1. ✅ **文件选择与上传**：点击按钮选择文件，自动上传到文件库
2. ✅ **文件大小验证**：根据 `max_size_mb` 约束验证
3. ✅ **扩展名过滤**：根据 `allowed_extensions` 约束过滤
4. ✅ **多文件支持**：如果 `multiple=true`，可以上传多个文件
5. ✅ **已上传文件展示**：显示已上传文件的 ID 列表
6. ✅ **移除功能**：可以移除已上传的文件
7. ✅ **执行中禁用**：任务执行时禁用上传和删除按钮

---

## 使用流程

### 配置阶段

1. 在 StartNode 中添加文件类型变量
2. 配置约束：
   - ✅ **必填**：是否必须提供文件
   - **允许的扩展名**：如 `.pdf`, `.txt`, `.docx`
   - **最大大小**：如 `10` MB
   - **允许多文件**：是否允许上传多个文件

### 测试运行阶段

1. 点击"测试运行"按钮
2. 在弹出的表单中：
   - 看到文件类型的输入框
   - 点击"选择文件"按钮
   - 选择文件后自动上传
   - 上传成功后显示文件 ID
   - 可以移除已上传的文件
3. 填写其他必填项
4. 点击"运行"按钮执行任务

---

## 后端验证

后端 `StartNodeExecutor` 已经支持文件变量的验证：

```python
# backend/app/engine/workflow/node_executor.py
if var_type == 'file':
    resolved, err = await validate_file_variable(raw_value, var_def)
    if err:
        errors.append(f"变量 '{var_name}': {err}")
    else:
        resolved_values[var_name] = resolved

# 必填检查
if is_required and (raw_value is None or raw_value == '' or raw_value == []):
    missing_required.append(var_name)
```

文件验证器 `file_validator.py` 会检查：
- ✅ FileRef 存在性
- ✅ 扩展名约束
- ✅ 大小约束
- ✅ 多文件约束

---

## 测试验证

### 前端编译测试

```bash
$ cd frontend && npm run build
✓ 3380 modules transformed.
✓ built in 1.74s
```

编译成功，无错误。

### 功能测试清单

- [ ] 配置文件变量时可以看到"必填"开关
- [ ] 测试运行时可以看到文件上传按钮
- [ ] 上传文件后显示文件 ID
- [ ] 可以移除已上传的文件
- [ ] 多文件模式下可以上传多个文件
- [ ] 文件大小验证生效
- [ ] 扩展名过滤生效
- [ ] 必填验证生效

---

## 相关文件

### 修改的文件

1. `frontend/src/features/workflow-editor/utils/variable-types.ts`
   - 为 file 类型添加 `required` 约束字段

2. `frontend/src/pages/workflow-detail-page.tsx`
   - 导入 `Upload`、`UploadOutlined`、`DeleteOutlined`
   - 导入 `filesApi`、`getFileId`
   - 在 `VariableFormField` 中添加 file case

### 新增的文件

1. `frontend/src/services/files-api.ts`
   - 通用文件上传 API 服务

---

## 后续优化建议

1. **文件预览**：在上传后显示文件预览（图片缩略图、PDF 预览等）
2. **拖拽上传**：支持拖拽文件到上传区域
3. **批量上传**：多文件模式下支持批量选择
4. **上传进度**：显示上传进度条
5. **文件详情**：显示文件名、大小、类型等详细信息
