use serde_json::{json, Value};
use std::{fs, path::Path};

pub fn read(path: &Path) -> bool {
    fs::read(path).ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .is_some_and(|value| value["closeBehavior"] == "exit")
}

pub fn save(path: &Path, behavior: &str) -> Result<bool, String> {
    if !matches!(behavior, "tray" | "exit") {
        return Err("无效的窗口关闭行为。".into());
    }
    let parent = path.parent().ok_or("无法确定设置目录。")?;
    fs::create_dir_all(parent).map_err(|e| format!("无法创建设置目录：{e}"))?;
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    fs::write(&temporary, json!({"closeBehavior": behavior}).to_string())
        .map_err(|e| format!("无法保存关闭行为：{e}"))?;
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(&temporary);
        return Err(format!("无法保存关闭行为：{error}"));
    }
    Ok(behavior == "exit")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persists_choices_and_preserves_file_on_invalid_input() {
        let unique = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let directory = std::env::temp_dir().join(format!("omi-window-settings-{}-{unique}", std::process::id()));
        let path = directory.join("window.json");
        assert!(!read(&path));
        assert!(save(&path, "exit").unwrap());
        assert!(read(&path));
        let before = fs::read(&path).unwrap();
        assert!(save(&path, "invalid").is_err());
        assert_eq!(fs::read(&path).unwrap(), before);
        assert!(!save(&path, "tray").unwrap());
        assert!(!read(&path));
        fs::write(&path, b"broken").unwrap();
        assert!(!read(&path));
        fs::write(&path, br#"{"closeBehavior":"future-value"}"#).unwrap();
        assert!(!read(&path));
        fs::remove_file(&path).unwrap();
        fs::remove_dir(&directory).unwrap();
    }

    #[test]
    fn unwritable_destination_returns_error() {
        assert!(save(Path::new(""), "exit").is_err());
    }
}
