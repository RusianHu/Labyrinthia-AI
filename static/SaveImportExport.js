// Labyrinthia AI - 存档导入/导出模块
// 提供存档的导入和导出功能

// 扩展核心游戏类，添加导入/导出功能
Object.assign(LabyrinthiaGame.prototype, {
    
    /**
     * 导出存档为JSON文件
     * @param {string} saveId - 存档ID
     */
    async exportSave(saveId) {
        try {
            this.addMessage('正在导出存档...', 'info');
            
            // 调用导出API
            const response = await fetch(`/api/save/export/${saveId}`);
            
            if (!response.ok) {
                throw new Error('导出失败');
            }
            
            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'save.json';
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="(.+)"/);
                if (filenameMatch) {
                    filename = filenameMatch[1];
                }
            }
            
            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            this.addMessage('存档导出成功！', 'success');
            
        } catch (error) {
            console.error('Export error:', error);
            this.addMessage('导出存档失败', 'error');
        }
    },
    
    /**
     * 显示导入存档对话框
     */
    showImportDialog() {
        // 创建文件输入元素
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.json,application/json';
        fileInput.style.display = 'none';
        
        fileInput.onchange = async (e) => {
            const file = e.target.files[0];
            if (file) {
                await this.importSave(file);
            }
            document.body.removeChild(fileInput);
        };
        
        document.body.appendChild(fileInput);
        fileInput.click();
    },
    
    /**
     * 导入存档文件
     * @param {File} file - 存档文件
     */
    async importSave(file) {
        try {
            this.setLoading(true);
            this.addMessage('正在导入存档...', 'info');
            
            // 验证文件类型
            if (!file.name.endsWith('.json')) {
                throw new Error('请选择JSON格式的存档文件');
            }
            
            // 创建FormData
            const formData = new FormData();
            formData.append('file', file);
            
            // 调用导入API
            const response = await fetch('/api/save/import', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.addMessage('存档导入成功！', 'success');
                
                // 刷新存档列表
                await this.loadGameList();
                
                // 询问是否立即加载
                if (confirm('存档导入成功！是否立即加载这个存档？')) {
                    await this.loadGame(result.save_id);
                }
            } else {
                throw new Error(result.message || '导入失败');
            }
            
        } catch (error) {
            console.error('Import error:', error);
            this.addMessage(`导入存档失败: ${error.message}`, 'error');
        } finally {
            this.setLoading(false);
        }
    },
    
    /**
     * 获取用户统计信息
     */
    async getUserStats() {
        try {
            const response = await fetch('/api/user/stats');
            const stats = await response.json();
            return stats;
        } catch (error) {
            console.error('Failed to get user stats:', error);
            return null;
        }
    },
    
    /**
     * 显示用户统计信息
     */
    async showUserStats() {
        const stats = await this.getUserStats();
        if (stats) {
            const message = `
                📊 用户统计
                存档数量: ${stats.total_saves}
                总游戏回合: ${stats.total_playtime}
                最高等级: ${stats.highest_level}
            `;
            alert(message);
        }
    }
});

// 注意：导出按钮现在直接在SaveManager.js的loadGameList()中生成
// 不需要额外的DOM操作来添加导出按钮

